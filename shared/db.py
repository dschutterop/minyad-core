"""Shared async SQLAlchemy session factory and encrypted settings helpers."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from functools import lru_cache

from cryptography.fernet import Fernet
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DB_URL_ENV = "DB_URL"
ENCRYPTION_KEY_ENV = "ENCRYPTION_KEY"


def get_db_url() -> str:
    """Return the bootstrap database URL supplied by the environment."""
    return os.environ[DB_URL_ENV]


engine = create_async_engine(get_db_url(), pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


@lru_cache(maxsize=1)
def get_fernet() -> Fernet:
    """Build a Fernet instance for settings marked encrypted in PostgreSQL."""
    raw_key = os.environ.get(ENCRYPTION_KEY_ENV)
    if not raw_key:
        raise ValueError(f"{ENCRYPTION_KEY_ENV} must be set to a Fernet key")
    return Fernet(raw_key.encode())


def encrypt_setting(plaintext: str) -> str:
    """Encrypt a runtime setting before storing it in the settings.value column."""
    return get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_setting(ciphertext: str) -> str:
    """Decrypt a runtime setting read from the settings.value column."""
    return get_fernet().decrypt(ciphertext.encode()).decode()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding an async database session."""
    async with AsyncSessionLocal() as session:
        yield session
