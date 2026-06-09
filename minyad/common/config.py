from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(
        "postgresql://minyad:minyad@postgres:5432/minyad", alias="DATABASE_URL"
    )
    timezone: str = Field("Europe/Amsterdam", alias="MINYAD_TIMEZONE")

    mqtt_host: str = Field("mosquitto", alias="MQTT_HOST")
    mqtt_port: int = Field(1883, alias="MQTT_PORT")
    mqtt_username: str | None = Field(None, alias="MQTT_USERNAME")
    mqtt_password: str | None = Field(None, alias="MQTT_PASSWORD")
    dsmr_mqtt_topic: str = Field("dsmr/reading", alias="DSMR_MQTT_TOPIC")

    envoy_host: str = Field("envoy.local", alias="ENVOY_HOST")
    envoy_username: str = Field("installer", alias="ENVOY_USERNAME")
    envoy_password: str = Field("", alias="ENVOY_PASSWORD")

    goodwe_host: str = Field("goodwe.local", alias="GOODWE_HOST")
    goodwe_modbus_port: int = Field(502, alias="GOODWE_MODBUS_PORT")
    goodwe_station_id: int = Field(247, alias="GOODWE_STATION_ID")

    latitude: float = Field(52.3676, alias="MINYAD_LATITUDE")
    longitude: float = Field(4.9041, alias="MINYAD_LONGITUDE")
    pv_peak_kw: float = Field(5.0, alias="PV_PEAK_KW")
    pv_performance_ratio: float = Field(0.78, alias="PV_PERFORMANCE_RATIO")

    http_timeout_s: float = Field(5.0, alias="HTTP_TIMEOUT_S")
    prometheus_port: int = Field(8001, alias="PROMETHEUS_PORT")

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_config() -> AppConfig:
    return AppConfig()
