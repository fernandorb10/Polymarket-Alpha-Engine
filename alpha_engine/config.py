from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    database_path: str = "data/alpha_engine.db"
    bankroll_usdc: float = 1000.0
    min_liquidity_usdc: float = 10_000.0
    min_volume_usdc: float = 5_000.0
    min_edge: float = 0.08
    max_spread: float = 0.04
    max_position_pct: float = 0.02
    ai_enabled: bool = True
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"


settings = Settings()
