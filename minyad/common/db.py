from collections.abc import Iterable
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Json

from minyad.common.config import get_config
from minyad.common.time import utc_now

DEFAULT_SETTINGS: dict[str, tuple[str, str]] = {
    "export_tolerance_w": ("50", "Max toegestane export in Watt"),
    "min_soc_pct": ("15", "Minimale SOC voor ontladen"),
    "max_soc_pct": ("95", "Maximale SOC voor laden"),
    "charge_threshold_w": ("200", "Min solar-overschot om te starten met laden"),
    "control_loop_interval_s": ("10", "Control loop interval in seconden"),
    "forecast_lookahead_h": ("36", "Uren vooruit voor forecast"),
    "enphase_poll_interval_s": ("10", "Poll interval Enphase Envoy"),
    "goodwe_poll_interval_s": ("5", "Poll interval GoodWe"),
    "forecast_refresh_interval_s": ("21600", "Forecast refresh interval in seconden"),
    "strategy": ("zero_export_self_consumption", "Actieve strategie"),
    "battery_max_charge_w": ("4600", "Max laadvermogen batterij"),
    "battery_max_discharge_w": ("4600", "Max ontlaadvermogen batterij"),
    "min_forecast_soc_pct": ("35", "Min SOC bij lage zonverwachting"),
    "low_solar_forecast_kwh": ("8", "Drempel voor lage verwachte productie morgen"),
}


@contextmanager
def connect():
    conn = psycopg.connect(get_config().database_url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def seed_default_settings(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for key, (value, description) in DEFAULT_SETTINGS.items():
            cur.execute(
                """
                INSERT INTO settings (key, value, description)
                VALUES (%s, %s, %s)
                ON CONFLICT (key) DO NOTHING
                """,
                (key, value, description),
            )


def get_settings(conn: psycopg.Connection) -> dict[str, str]:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}


def setting_int(settings: dict[str, str], key: str, default: int) -> int:
    try:
        return int(float(settings.get(key, default)))
    except (TypeError, ValueError):
        return default


def setting_float(settings: dict[str, str], key: str, default: float) -> float:
    try:
        return float(settings.get(key, default))
    except (TypeError, ValueError):
        return default


def insert_reading(conn: psycopg.Connection, table: str, data: dict[str, Any]) -> None:
    columns = list(data.keys())
    placeholders = ", ".join(["%s"] * len(columns))
    names = ", ".join(columns)
    values = [Json(v) if isinstance(v, dict) else v for v in data.values()]
    with conn.cursor() as cur:
        cur.execute(f"INSERT INTO {table} ({names}) VALUES ({placeholders})", values)


def latest(conn: psycopg.Connection, table: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} ORDER BY timestamp DESC LIMIT 1")
        return cur.fetchone()


def latest_forecast(conn: psycopg.Connection, hours: int = 24) -> list[dict[str, Any]]:
    now = utc_now()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT ON (timestamp_target) *
            FROM solar_forecast
            WHERE timestamp_target >= %s AND timestamp_target <= %s
            ORDER BY timestamp_target, timestamp_forecast DESC
            """,
            (now, now + timedelta(hours=hours)),
        )
        return cur.fetchall()


def recent_control_log(conn: psycopg.Connection, limit: int = 20) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM control_log ORDER BY timestamp DESC LIMIT %s", (limit,))
        return cur.fetchall()


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    return value


def bulk_insert_forecast(conn: psycopg.Connection, rows: Iterable[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO solar_forecast (timestamp_forecast, timestamp_target, ghi_wm2, dni_wm2, cloud_cover_pct, predicted_w)
            VALUES (%(timestamp_forecast)s, %(timestamp_target)s, %(ghi_wm2)s, %(dni_wm2)s, %(cloud_cover_pct)s, %(predicted_w)s)
            ON CONFLICT (timestamp_forecast, timestamp_target) DO UPDATE
            SET ghi_wm2 = EXCLUDED.ghi_wm2,
                dni_wm2 = EXCLUDED.dni_wm2,
                cloud_cover_pct = EXCLUDED.cloud_cover_pct,
                predicted_w = EXCLUDED.predicted_w
            """,
            list(rows),
        )
