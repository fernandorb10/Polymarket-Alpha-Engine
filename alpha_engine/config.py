from pathlib import Path
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    ai_provider: str = 'openai'
    ai_enabled: bool = True
    openai_api_key: str | None = None
    openai_model: str = 'gpt-5-mini'
    gemini_api_key: str | None = None
    gemini_model: str = 'gemini-3.5-flash-lite'
    gemini_base_url: str = 'https://generativelanguage.googleapis.com/v1beta/openai/'

    database_path: str = './data/alpha_engine.db'
    report_dir: str = './reports'
    backup_dir: str = './backups'
    export_dir: str = './exports'
    log_level: str = 'INFO'
    gamma_url: str = 'https://gamma-api.polymarket.com'
    clob_url: str = 'https://clob.polymarket.com'
    http_timeout: float = 30
    scan_limit: int = 1000
    analysis_top_n: int = 12
    analysis_cooldown_minutes: int = 180

    min_liquidity: float = 5000
    min_volume: float = 10000
    max_spread: float = Field(default=0.08, ge=0, le=1)
    min_price: float = Field(default=0.05, ge=0, le=1)
    max_price: float = Field(default=0.95, ge=0, le=1)
    min_hours_to_close: float = 6
    min_net_edge: float = Field(default=0.06, ge=0, le=1)
    min_confidence: float = Field(default=0.55, ge=0, le=1)
    max_critic_risk: float = Field(default=0.65, ge=0, le=1)

    bankroll_usdc: float = Field(default=1000, gt=0)
    kelly_fraction: float = Field(default=0.25, ge=0, le=1)
    max_position_pct: float = Field(default=0.05, gt=0, le=1)
    max_total_exposure_pct: float = Field(default=0.35, gt=0, le=1)
    max_event_exposure_pct: float = Field(default=0.05, gt=0, le=1)
    max_category_exposure_pct: float = Field(default=0.10, gt=0, le=1)
    max_related_positions: int = Field(default=2, ge=1)
    max_new_positions_per_day: int = Field(default=3, ge=0)
    daily_loss_limit_pct: float = Field(default=0.03, gt=0, le=1)
    pause_drawdown_pct: float = Field(default=0.10, gt=0, le=1)

    slippage_buffer: float = Field(default=0.01, ge=0, le=1)
    paper_execution_slippage_pct: float = Field(default=0.0025, ge=0, le=0.2)
    paper_fee_pct: float = Field(default=0.001, ge=0, le=0.2)
    max_ai_calls_per_cycle: int = Field(default=12, ge=0)

    take_profit_pct: float = Field(default=0.15, gt=0, le=5)
    stop_loss_pct: float = Field(default=0.10, gt=0, le=1)
    trailing_stop_pct: float = Field(default=0.06, gt=0, le=1)
    trailing_activation_pct: float = Field(default=0.08, gt=0, le=5)
    exit_min_edge: float = Field(default=0.02, ge=0, le=1)
    exit_confirmation_cycles: int = Field(default=2, ge=1)
    entry_confirmation_cycles: int = Field(default=2, ge=1)
    exit_hours_to_resolution: float = 24
    max_position_age_days: int = Field(default=180, ge=1)
    reopen_cooldown_days: int = Field(default=14, ge=0)

    circuit_breaker_failures: int = Field(default=3, ge=1)
    circuit_breaker_cooldown_minutes: int = Field(default=60, ge=1)
    snapshot_retention_days: int = Field(default=90, ge=1)
    ledger_retention_days: int = Field(default=365, ge=1)
    backup_retention_days: int = Field(default=30, ge=1)
    strategy_version: str = 'V4'
    campaign_id: str = 'paper-2026-v4'

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    dashboard_host: str = '0.0.0.0'
    dashboard_port: int = 8080
    dashboard_refresh_seconds: int = 30
    stale_cycle_minutes: int = 30
    dashboard_username: str | None = None
    dashboard_password: str | None = None

    @model_validator(mode='after')
    def validate_limits(self):
        if self.min_price >= self.max_price:
            raise ValueError('MIN_PRICE must be lower than MAX_PRICE')
        if self.max_position_pct > self.max_total_exposure_pct:
            raise ValueError('MAX_POSITION_PCT cannot exceed MAX_TOTAL_EXPOSURE_PCT')
        if self.max_event_exposure_pct > self.max_category_exposure_pct:
            raise ValueError('MAX_EVENT_EXPOSURE_PCT cannot exceed MAX_CATEGORY_EXPOSURE_PCT')
        return self

    def ensure_dirs(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.report_dir).mkdir(parents=True, exist_ok=True)
        Path(self.backup_dir).mkdir(parents=True, exist_ok=True)
        Path(self.export_dir).mkdir(parents=True, exist_ok=True)


settings = Settings()
