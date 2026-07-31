from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    ai_provider: str = "openai"
    ai_enabled: bool = True

    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"

    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"

    database_path: str = "./data/alpha_engine.db"
    report_dir: str = "./reports"
    log_level: str = "INFO"
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    http_timeout: float = 30
    scan_limit: int = 1000
    analysis_top_n: int = 12
    analysis_cooldown_minutes: int = 180
    min_liquidity: float = 5000
    min_volume: float = 10000
    max_spread: float = 0.08
    min_price: float = 0.05
    max_price: float = 0.95
    min_hours_to_close: float = 6
    min_net_edge: float = 0.06
    min_confidence: float = 0.55
    max_critic_risk: float = 0.65
    bankroll_usdc: float = 1000
    kelly_fraction: float = 0.25
    max_position_pct: float = 0.05
    max_total_exposure_pct: float = 0.35
    slippage_buffer: float = 0.01
    max_ai_calls_per_cycle: int = 12

    take_profit_pct: float = 0.15
    stop_loss_pct: float = 0.10
    exit_min_edge: float = 0.02
    exit_hours_to_resolution: float = 24

    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    dashboard_refresh_seconds: int = 30
    stale_cycle_minutes: int = 30

    def ensure_dirs(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
