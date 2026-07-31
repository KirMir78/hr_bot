import hashlib
import hmac
import time
from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import User

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 30
AUTH_DATE_MAX_AGE_SECONDS = 86400  # хэш логина считаем валидным сутки

bearer_scheme = HTTPBearer()


def verify_telegram_login(data: dict) -> bool:
    """
    Проверяет подпись данных, присланных Telegram Login Widget.
    Алгоритм из офиц. доков: https://core.telegram.org/widgets/login#checking-authorization
    """
    received_hash = data.get("hash")
    if not received_hash:
        return False

    check_fields = {k: v for k, v in data.items() if k != "hash" and v is not None}
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(check_fields.items()))

    secret_key = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return False

    auth_date = int(data.get("auth_date", 0))
    if time.time() - auth_date > AUTH_DATE_MAX_AGE_SECONDS:
        return False

    return True


def get_or_create_user(db: Session, data: dict) -> User:
    telegram_id = str(data["id"])
    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    if user is None:
        user = User(
            telegram_id=telegram_id,
            first_name=data.get("first_name"),
            last_name=data.get("last_name"),
            username=data.get("username"),
            photo_url=data.get("photo_url"),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def create_access_token(user: User) -> str:
    expire = datetime.utcnow() + timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user.id), "telegram_id": user.telegram_id, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалидный токен")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Пользователь не найден")
    return user
