from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    MONGO_URI: str = "mongodb://localhost:27017"
    DB_NAME: str = "emergency_routing"
    PORT: int = 8000
    AVG_URBAN_SPEED_KMH: float = 30.0
    ROUTING_PROVIDER: str = "haversine"
    ROUTING_API_KEY: str = ""
    ALERT_RESPONSE_TIMEOUT_SECONDS: int = 30
    MAX_STATUS_AGE_SECONDS: int = 600
    WS_KEEPALIVE_SECONDS: int = 30


settings = Settings()
