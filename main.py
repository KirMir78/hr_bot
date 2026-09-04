from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import settings
from database import Base, engine, get_db
from models import User, Message
from auth import verify_telegram_login, get_or_create_user, create_access_token, get_current_user
from agent import get_agent_reply
import logging

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s %(name)s: %(message)s'
)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="HR Agent API")

# На dev по умолчанию открыт localhost, на проде укажите свой домен в ALLOWED_ORIGIN
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.allowed_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- схемы запросов/ответов ----------

class TelegramLoginData(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


# ---------- auth ----------

@app.post("/auth/telegram")
def auth_telegram(data: TelegramLoginData, db: Session = Depends(get_db)):
    data_dict = data.model_dump()
    if not verify_telegram_login(data_dict):
        raise HTTPException(status_code=401, detail="Проверка подписи Telegram не пройдена")

    user = get_or_create_user(db, data_dict)
    token = create_access_token(user)
    return {"access_token": token, "user": {"id": user.id, "first_name": user.first_name}}


@app.post("/auth/dev-login")
def dev_login(db: Session = Depends(get_db)):
    """
    Только для локальной разработки: логинит под тестовым пользователем без
    прохождения Telegram Login Widget (виджет требует зарегистрированный
    https-домен через BotFather, что неудобно на локалхосте).
    """
    if settings.app_env != "dev":
        raise HTTPException(status_code=404)

    fake_data = {
        "id": "000000001",
        "first_name": "Test",
        "last_name": "User",
        "username": "test_user",
        "auth_date": 0,
    }
    user = db.query(User).filter(User.telegram_id == fake_data["id"]).first()
    if user is None:
        user = User(telegram_id=fake_data["id"], first_name="Test", last_name="User", username="test_user")
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(user)
    return {"access_token": token, "user": {"id": user.id, "first_name": user.first_name}}


# ---------- chat ----------

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # сохраняем сообщение пользователя
    db.add(Message(user_id=user.id, role="user", content=req.message))
    db.commit()

    # берём последние N сообщений как контекст диалога
    history_rows = (
        db.query(Message)
        .filter(Message.user_id == user.id)
        .order_by(Message.created_at.desc())
        .limit(20)
        .all()
    )
    history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]

    # ВАЖНО: добавляем await
    reply = await get_agent_reply(history)

    db.add(Message(user_id=user.id, role="assistant", content=reply))
    db.commit()

    return ChatResponse(reply=reply)


@app.get("/chat/history")
def chat_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = (
        db.query(Message)
        .filter(Message.user_id == user.id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return [{"role": m.role, "content": m.content, "created_at": m.created_at.isoformat()} for m in rows]

@app.delete("/chat/history")
def clear_chat_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Удаляет всю историю диалога текущего пользователя."""
    db.query(Message).filter(Message.user_id == user.id).delete()
    db.commit()
    return {"status": "ok", "message": "История очищена"}

@app.get("/health")
def health():
    return {"status": "ok"}
