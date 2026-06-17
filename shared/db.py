"""Shared SQLAlchemy setup and encrypted setting primitives."""

from __future__ import annotations

import os
from collections.abc import Iterator

from cryptography.fernet import Fernet
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DB_URL = os.environ["DB_URL"]
ENCRYPTION_KEY = os.environ["ENCRYPTION_KEY"].encode()

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
fernet = Fernet(ENCRYPTION_KEY)


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    encrypted_value: Mapped[str | None] = mapped_column(String, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def set_secret(self, plaintext: str) -> None:
        self.encrypted_value = fernet.encrypt(plaintext.encode()).decode()
        self.value = None
        self.is_secret = True

    def get_secret(self) -> str | None:
        if not self.encrypted_value:
            return None
        return fernet.decrypt(self.encrypted_value.encode()).decode()


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_key: Mapped[str] = mapped_column(String, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
