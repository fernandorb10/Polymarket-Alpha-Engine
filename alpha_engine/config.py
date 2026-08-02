from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    ai_provider: str = "openai"
    ai_enabled: bool = True
    openai_api_key: str | None = None
    openai_model: str = "gpt-5-mini"
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    web_research_enabled: bool = True
    web_research_max_items: int = Field(default=8, ge=1, le=20)
    web_research_timeout: float = Field(default=10, gt=0)
    require_web_evidence: bool = True
    min_evidence_sources: int = Field(default=2, ge=1, le=10)

    database_path: str = "./data/alpha_engine.db"
    report_dir: str = "./reports"
    backup_dir: str = "./backups"
    export_dir: str = "./exports"
    log_level: str = "INFO"
    gamma_url: str = "https://gamma-api.polymarket.com"
    clob_url: str = "https://clob.polymarket.com"
    http_timeout: float = 30
    scan_limit: int = Field(default=1000, ge=100)
    scan_page_size: int = Field(default=100, ge=10, le=100)
    analysis_top_n: int = 7
    analysis_cooldown_minutes: int = 180
    diversity_cooldown_minutes: int = Field(default=30, ge=0)
    diversify_analysis: bool = True
    analysis_categories: str = (
        "sports,crypto,economy,politics,technology,entertainment,other"
    )
    max_analysis_per_category: int = Field(default=2, ge=1)
    discovery_budget_fraction: float = Field(default=0.40, ge=0.1, le=0.9)

    min_liquidity: float = 10000
    min_volume: float = 25000
    max_spread: float = Field(default=0.03, ge=0, le=1)
    min_price: float = Field(default=0.15, ge=0, le=1)
    max_price: float = Field(default=0.85, ge=0, le=1)
    min_hours_to_close: float = 12
    max_hours_to_close: float = Field(default=336, gt=0)
    min_net_edge: float = Field(default=0.10, ge=0, le=1)
    min_edge_cost_multiple: float = Field(default=2.5, ge=1)
    min_confidence: float = Field(default=0.65, ge=0, le=1)
    max_critic_risk: float = Field(default=0.45, ge=0, le=1)

    bankroll_usdc: float = Field(default=1000, gt=0)
    kelly_fraction: float = Field(default=0.10, ge=0, le=1)
    max_position_pct: float = Field(default=0.02, gt=0, le=1)
    max_total_exposure_pct: float = Field(default=0.10, gt=0, le=1)
    max_event_exposure_pct: float = Field(default=0.02, gt=0, le=1)
    max_category_exposure_pct: float = Field(default=0.04, gt=0, le=1)
    max_related_positions: int = Field(default=1, ge=1)
    max_new_positions_per_day: int = Field(default=1, ge=0)
    daily_loss_limit_pct: float = Field(default=0.01, gt=0, le=1)
    pause_drawdown_pct: float = Field(default=0.05, gt=0, le=1)

    slippage_buffer: float = Field(default=0.005, ge=0, le=1)
    paper_execution_slippage_pct: float = Field(default=0.0025, ge=0, le=0.2)
    paper_fee_pct: float = Field(default=0.001, ge=0, le=0.2)
    max_ai_calls_per_cycle: int = Field(default=14, ge=0)

    take_profit_pct: float = Field(default=0.20, gt=0, le=5)
    stop_loss_pct: float = Field(default=0.20, gt=0, le=1)
    trailing_stop_pct: float = Field(default=0.12, gt=0, le=1)
    trailing_activation_pct: float = Field(default=0.15, gt=0, le=5)
    edge_exit_enabled: bool = False
    exit_min_edge: float = Field(default=0.00, ge=0, le=1)
    exit_confirmation_cycles: int = Field(default=4, ge=1)
    entry_confirmation_cycles: int = Field(default=3, ge=1)
    entry_confirmation_expiry_minutes: int = Field(default=240, ge=1)
    exit_hours_to_resolution: float = 6
    max_position_age_days: int = Field(default=21, ge=1)
    reopen_cooldown_days: int = Field(default=30, ge=0)

    circuit_breaker_failures: int = Field(default=3, ge=1)
    circuit_breaker_cooldown_minutes: int = Field(default=60, ge=1)
    snapshot_retention_days: int = Field(default=90, ge=1)
    ledger_retention_days: int = Field(default=365, ge=1)
    backup_retention_days: int = Field(default=30, ge=1)
    maintenance_min_interval_hours: int = Field(default=20, ge=1)
    strategy_version: str = "V6"
    campaign_id: str = "paper-2026-v6"

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8080
    dashboard_refresh_seconds: int = 30
    stale_cycle_minutes: int = 30
    dashboard_username: str | None = None
    dashboard_password: str | None = None

    @property
    def analysis_category_list(self) -> list[str]:
        return [
            item.strip().lower()
            for item in self.analysis_categories.split(",")
            if item.strip()
        ]

    @model_validator(mode="after")
    def validate_limits(self):
        if self.min_price >= self.max_price:
            raise ValueError("MIN_PRICE must be lower than MAX_PRICE")
        if self.min_hours_to_close >= self.max_hours_to_close:
            raise ValueError("MIN_HOURS_TO_CLOSE must be lower than MAX_HOURS_TO_CLOSE")
        if self.max_position_pct > self.max_total_exposure_pct:
            raise ValueError(
                "MAX_POSITION_PCT cannot exceed MAX_TOTAL_EXPOSURE_PCT"
            )
        if self.max_event_exposure_pct > self.max_category_exposure_pct:
            raise ValueError(
                "MAX_EVENT_EXPOSURE_PCT cannot exceed MAX_CATEGORY_EXPOSURE_PCT"
            )
        if self.diversity_cooldown_minutes > self.analysis_cooldown_minutes:
            raise ValueError(
                "DIVERSITY_COOLDOWN_MINUTES cannot exceed ANALYSIS_COOLDOWN_MINUTES"
            )
        return self

    def validate_dashboard_security(self, host: str | None = None) -> None:
        bind_host = host or self.dashboard_host
        if bind_host in {"0.0.0.0", "::"} and not (
            self.dashboard_username and self.dashboard_password
        ):
            raise ValueError(
                "Public dashboard binding requires DASHBOARD_USERNAME and "
                "DASHBOARD_PASSWORD"
            )

    def ensure_dirs(self) -> None:
        for path in (
            Path(self.database_path).parent,
            Path(self.report_dir),
            Path(self.backup_dir),
            Path(self.export_dir),
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings()
