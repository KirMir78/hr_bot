from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    telegram_bot_token: str
    telegram_bot_username: str
    deepseek_api_key: str
    jwt_secret: str
    app_env: str = "dev"
    # Домен, с которого разрешено обращаться к API (ваш фронт).
    # На dev можно оставить http://localhost:8080 или что у вас там открыто.
    allowed_origin: str = "http://localhost:8080"

    database_url: str = "sqlite:///./hr_agent.db"

    # --- Добавь эту строку ---
    allowed_users: str = ""

    class Config:
        env_file = ".env"


settings = Settings()
