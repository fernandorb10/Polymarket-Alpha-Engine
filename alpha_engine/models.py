from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field

class Market(BaseModel):
    id: str
    condition_id: str = ""
    question: str
    slug: str = ""
    rules: str = ""
    category: str = "unknown"
    end_date: datetime | None = None
    active: bool = True
    closed: bool = False
    yes_token_id: str = ""
    no_token_id: str = ""
    yes_price: float
    no_price: float
    best_bid_yes: float | None = None
    best_ask_yes: float | None = None
    spread: float = 0
    liquidity: float = 0
    volume: float = 0
    volume_24h: float = 0
    rank_score: float = 0
    raw: dict = Field(default_factory=dict)

class ProbabilityReport(BaseModel):
    probability_yes: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    thesis: str
    evidence: list[str] = Field(default_factory=list)
    counterarguments: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

class CriticReport(BaseModel):
    risk_score: float = Field(ge=0, le=1)
    resolution_ambiguity: float = Field(ge=0, le=1)
    strongest_objection: str
    failure_modes: list[str] = Field(default_factory=list)
    recommendation: Literal["ACCEPT", "REDUCE", "REJECT"]

class Opportunity(BaseModel):
    market: Market
    side: Literal["YES", "NO"]
    fair_probability: float
    market_probability: float
    gross_edge: float
    net_edge: float
    expected_value_per_dollar: float
    confidence: float
    critic_risk: float
    kelly_fraction: float
    stake_usdc: float
    score: float
    decision: Literal["OPEN", "WATCH", "REJECT"]
    reason: str
    probability_report: ProbabilityReport
    critic_report: CriticReport
