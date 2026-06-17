"""Shared SQLAlchemy setup and encrypted setting primitives."""

from __future__ import annotations

import os
from collections.abc import Iterator
from functools import lru_cache

from cryptography.fernet import Fernet
from sqlalchemy import Boolean, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

DB_URL = os.environ["DB_URL"]
ENCRYPTION_KEY_ENV = "ENCRYPTION_KEY"

engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Build the Fernet instance when encrypted values are actually used."""
    raw_key = os.environ.get(ENCRYPTION_KEY_ENV)
    if not raw_key:
        raise ValueError(
            f"{ENCRYPTION_KEY_ENV} must be set to a Fernet key. Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )

    try:
        return Fernet(raw_key.encode())
    except ValueError as exc:
        raise ValueError(
            f"{ENCRYPTION_KEY_ENV} must be a 32-byte url-safe base64-encoded Fernet key. "
            "Generate one with: python -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        ) from exc


class Base(DeclarativeBase):
    pass


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str | None] = mapped_column(String, nullable=True)
    encrypted_value: Mapped[str | None] = mapped_column(String, nullable=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    def set_secret(self, plaintext: str) -> None:
        self.encrypted_value = get_fernet().encrypt(plaintext.encode()).decode()
        self.value = None
        self.is_secret = True

    def get_secret(self) -> str | None:
        if not self.encrypted_value:
            return None
        return get_fernet().decrypt(self.encrypted_value.encode()).decode()


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
