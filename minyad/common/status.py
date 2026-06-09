from typing import Any

import psycopg
from psycopg.types.json import Json

from minyad.common.time import utc_now


def update_status(conn: psycopg.Connection, service: str, status: str, details: dict[str, Any] | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO service_status (service, status, updated_at, details)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (service) DO UPDATE
            SET status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at,
                details = EXCLUDED.details
            """,
            (service, status, utc_now(), Json(details or {})),
        )
