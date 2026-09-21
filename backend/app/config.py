import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    jwt_expire_minutes: int
    cors_origins: list
    db_pool_max: int
    bank_name: str


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set - copy backend/.env.example to backend/.env and fill it in")
    return value


@lru_cache
def get_settings() -> Settings:
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000")
    return Settings(
        database_url=_required("DATABASE_URL"),
        jwt_secret=_required("JWT_SECRET"),
        jwt_expire_minutes=int(os.environ.get("JWT_EXPIRE_MINUTES", "480")),
        cors_origins=[o.strip() for o in origins.split(",") if o.strip()],
        db_pool_max=int(os.environ.get("DB_POOL_MAX", "5")),
        bank_name=os.environ.get("BANK_NAME", "Bank X"),
    )
