export interface Env {
  DB: D1Database;

  AI_PROVIDER: string;
  AI_ENABLED: string;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL: string;
  GEMINI_API_KEY?: string;
  GEMINI_MODEL: string;
  GEMINI_BASE_URL: string;
  WEB_RESEARCH_ENABLED: string;
  WEB_RESEARCH_MAX_ITEMS: string;
  WEB_RESEARCH_TIMEOUT_MS: string;
  REQUIRE_WEB_EVIDENCE: string;
  MIN_EVIDENCE_SOURCES: string;

  GAMMA_URL: string;
  CLOB_URL: string;
  HTTP_TIMEOUT_MS: string;
  SCAN_LIMIT: string;
  SCAN_PAGE_SIZE: string;
  ANALYSIS_TOP_N: string;
  ANALYSIS_COOLDOWN_MINUTES: string;
  DIVERSITY_COOLDOWN_MINUTES: string;
  DIVERSIFY_ANALYSIS: string;
  ANALYSIS_CATEGORIES: string;
  MAX_ANALYSIS_PER_CATEGORY: string;
  DISCOVERY_BUDGET_FRACTION: string;

  MIN_LIQUIDITY: string;
  MIN_VOLUME: string;
  MAX_SPREAD: string;
  MIN_PRICE: string;
  MAX_PRICE: string;
  MIN_HOURS_TO_CLOSE: string;
  MAX_HOURS_TO_CLOSE: string;
  MIN_NET_EDGE: string;
  MIN_EDGE_COST_MULTIPLE: string;
  MIN_CONFIDENCE: string;
  MAX_CRITIC_RISK: string;

  BANKROLL_USDC: string;
  KELLY_FRACTION: string;
  MAX_POSITION_PCT: string;
  MAX_TOTAL_EXPOSURE_PCT: string;
  MAX_EVENT_EXPOSURE_PCT: string;
  MAX_CATEGORY_EXPOSURE_PCT: string;
  MAX_RELATED_POSITIONS: string;
  MAX_NEW_POSITIONS_PER_DAY: string;
  DAILY_LOSS_LIMIT_PCT: string;
  PAUSE_DRAWDOWN_PCT: string;

  SLIPPAGE_BUFFER: string;
  PAPER_EXECUTION_SLIPPAGE_PCT: string;
  PAPER_FEE_PCT: string;
  MAX_AI_CALLS_PER_CYCLE: string;

  TAKE_PROFIT_PCT: string;
  STOP_LOSS_PCT: string;
  TRAILING_STOP_PCT: string;
  TRAILING_ACTIVATION_PCT: string;
  EDGE_EXIT_ENABLED: string;
  EXIT_MIN_EDGE: string;
  EXIT_CONFIRMATION_CYCLES: string;
  ENTRY_CONFIRMATION_CYCLES: string;
  ENTRY_CONFIRMATION_EXPIRY_MINUTES: string;
  EXIT_HOURS_TO_RESOLUTION: string;
  MAX_POSITION_AGE_DAYS: string;
  REOPEN_COOLDOWN_DAYS: string;

  CIRCUIT_BREAKER_FAILURES: string;
  CIRCUIT_BREAKER_COOLDOWN_MINUTES: string;
  SNAPSHOT_RETENTION_DAYS: string;
  LEDGER_RETENTION_DAYS: string;
  MAINTENANCE_MIN_INTERVAL_HOURS: string;
  STRATEGY_VERSION: string;
  CAMPAIGN_ID: string;

  TELEGRAM_BOT_TOKEN?: string;
  TELEGRAM_CHAT_ID?: string;

  DASHBOARD_REFRESH_SECONDS: string;
  STALE_CYCLE_MINUTES: string;
  DASHBOARD_USERNAME?: string;
  DASHBOARD_PASSWORD?: string;
}

export interface Market {
  id: string;
  conditionId: string;
  question: string;
  slug: string;
  rules: string;
  category: string;
  endDate: string | null;
  active: boolean;
  closed: boolean;
  yesTokenId: string;
  noTokenId: string;
  yesPrice: number;
  noPrice: number;
  bestBidYes: number | null;
  bestAskYes: number | null;
  spread: number;
  liquidity: number;
  volume: number;
  volume24h: number;
  rankScore: number;
}

export interface ProbabilityReport {
  probability_yes: number;
  confidence: number;
  thesis: string;
  evidence: string[];
  counterarguments: string[];
  unknowns: string[];
  source_urls: string[];
}

export interface CriticReport {
  risk_score: number;
  resolution_ambiguity: number;
  strongest_objection: string;
  failure_modes: string[];
  recommendation: "ACCEPT" | "REDUCE" | "REJECT";
}

export type Side = "YES" | "NO";
export type Decision = "OPEN" | "WATCH" | "REJECT";

export interface Opportunity {
  market: Market;
  side: Side;
  fairProbability: number;
  marketProbability: number;
  grossEdge: number;
  netEdge: number;
  expectedValuePerDollar: number;
  confidence: number;
  criticRisk: number;
  kellyFraction: number;
  stakeUsdc: number;
  score: number;
  decision: Decision;
  reason: string;
  probabilityReport: ProbabilityReport;
  criticReport: CriticReport;
}

export interface EvidenceItem {
  title: string;
  source: string;
  published: string;
  url: string;
  query: string;
}
