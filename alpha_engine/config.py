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
    max_event_exposure_pct: float = 0.05
    max_category_exposure_pct: float = 0.10
    max_related_positions: int = 2

    slippage_buffer: float = 0.01
    paper_execution_slippage_pct: float = 0.0025
    paper_fee_pct: float = 0.001
    max_ai_calls_per_cycle: int = 12

    take_profit_pct: float = 0.15
    stop_loss_pct: float = 0.10
    trailing_stop_pct: float = 0.06
    trailing_activation_pct: float = 0.08
    exit_min_edge: float = 0.02
    exit_confirmation_cycles: int = 2
    exit_hours_to_resolution: float = 24
    max_position_age_days: int = 180

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 8080
    dashboard_refresh_seconds: int = 30
    stale_cycle_minutes: int = 30
    dashboard_username: str | None = None
    dashboard_password: str | None = None

    def ensure_dirs(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
