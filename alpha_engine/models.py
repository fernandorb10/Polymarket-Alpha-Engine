from datetime import datetime
from pydantic import BaseModel, Field


class Market(BaseModel):
    id: str
    condition_id: str = ""
    question: str
    slug: str = ""
    end_date: datetime | None = None
    liquidity: float = 0.0
    volume: float = 0.0
    yes_price: float
    no_price: float
    spread: float = 0.0
    active: bool = True
    closed: bool = False
    rules: str = ""


class ResearchReport(BaseModel):
    probability_yes: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    thesis: str
    counter_thesis: str
    catalysts: list[str] = []
    risks: list[str] = []
    source_urls: list[str] = []
    freshness_hours: float | None = None


class Opportunity(BaseModel):
    market: Market
    report: ResearchReport
    fair_probability: float
    market_probability: float
    gross_edge: float
    net_edge: float
    side: str
    score: float
    stake_usdc: float
    decision: str


class PaperPosition(BaseModel):
    id: int | None = None
    market_id: str
    question: str
    side: str
    entry_price: float
    shares: float
    stake_usdc: float
    opened_at: datetime
    status: str = "OPEN"
    exit_price: float | None = None
    closed_at: datetime | None = None
    pnl_usdc: float | None = None
