import type { Env } from "./types";

const num = (value: string | undefined, fallback: number): number =>
  value === undefined || value === "" ? fallback : Number(value);

const bool = (value: string | undefined, fallback: boolean): boolean =>
  value === undefined || value === "" ? fallback : value.toLowerCase() === "true";

export interface Settings {
  aiProvider: string;
  aiEnabled: boolean;
  openaiApiKey?: string;
  openaiModel: string;
  geminiApiKey?: string;
  geminiModel: string;
  geminiBaseUrl: string;
  webResearchEnabled: boolean;
  webResearchMaxItems: number;
  webResearchTimeoutMs: number;
  requireWebEvidence: boolean;
  minEvidenceSources: number;

  gammaUrl: string;
  clobUrl: string;
  httpTimeoutMs: number;
  scanLimit: number;
  scanPageSize: number;
  analysisTopN: number;
  analysisCooldownMinutes: number;
  diversityCooldownMinutes: number;
  diversifyAnalysis: boolean;
  analysisCategoryList: string[];
  maxAnalysisPerCategory: number;
  discoveryBudgetFraction: number;

  minLiquidity: number;
  minVolume: number;
  maxSpread: number;
  minPrice: number;
  maxPrice: number;
  minHoursToClose: number;
  maxHoursToClose: number;
  minNetEdge: number;
  minEdgeCostMultiple: number;
  minConfidence: number;
  maxCriticRisk: number;

  bankrollUsdc: number;
  kellyFraction: number;
  maxPositionPct: number;
  maxTotalExposurePct: number;
  maxEventExposurePct: number;
  maxCategoryExposurePct: number;
  maxRelatedPositions: number;
  maxNewPositionsPerDay: number;
  dailyLossLimitPct: number;
  pauseDrawdownPct: number;

  slippageBuffer: number;
  paperExecutionSlippagePct: number;
  paperFeePct: number;
  maxAiCallsPerCycle: number;

  takeProfitPct: number;
  stopLossPct: number;
  trailingStopPct: number;
  trailingActivationPct: number;
  edgeExitEnabled: boolean;
  exitMinEdge: number;
  exitConfirmationCycles: number;
  entryConfirmationCycles: number;
  entryConfirmationExpiryMinutes: number;
  exitHoursToResolution: number;
  maxPositionAgeDays: number;
  reopenCooldownDays: number;

  circuitBreakerFailures: number;
  circuitBreakerCooldownMinutes: number;
  snapshotRetentionDays: number;
  ledgerRetentionDays: number;
  maintenanceMinIntervalHours: number;
  strategyVersion: string;
  campaignId: string;

  telegramBotToken?: string;
  telegramChatId?: string;

  dashboardRefreshSeconds: number;
  staleCycleMinutes: number;
  dashboardUsername?: string;
  dashboardPassword?: string;
}

export function loadSettings(env: Env): Settings {
  return {
    aiProvider: env.AI_PROVIDER || "openai",
    aiEnabled: bool(env.AI_ENABLED, true),
    openaiApiKey: env.OPENAI_API_KEY,
    openaiModel: env.OPENAI_MODEL || "gpt-5-mini",
    geminiApiKey: env.GEMINI_API_KEY,
    geminiModel: env.GEMINI_MODEL || "gemini-3.5-flash-lite",
    geminiBaseUrl:
      env.GEMINI_BASE_URL || "https://generativelanguage.googleapis.com/v1beta/openai/",
    webResearchEnabled: bool(env.WEB_RESEARCH_ENABLED, true),
    webResearchMaxItems: num(env.WEB_RESEARCH_MAX_ITEMS, 8),
    webResearchTimeoutMs: num(env.WEB_RESEARCH_TIMEOUT_MS, 10000),
    requireWebEvidence: bool(env.REQUIRE_WEB_EVIDENCE, true),
    minEvidenceSources: num(env.MIN_EVIDENCE_SOURCES, 2),

    gammaUrl: env.GAMMA_URL || "https://gamma-api.polymarket.com",
    clobUrl: env.CLOB_URL || "https://clob.polymarket.com",
    httpTimeoutMs: num(env.HTTP_TIMEOUT_MS, 30000),
    scanLimit: num(env.SCAN_LIMIT, 1000),
    scanPageSize: num(env.SCAN_PAGE_SIZE, 100),
    analysisTopN: num(env.ANALYSIS_TOP_N, 7),
    analysisCooldownMinutes: num(env.ANALYSIS_COOLDOWN_MINUTES, 180),
    diversityCooldownMinutes: num(env.DIVERSITY_COOLDOWN_MINUTES, 30),
    diversifyAnalysis: bool(env.DIVERSIFY_ANALYSIS, true),
    analysisCategoryList: (
      env.ANALYSIS_CATEGORIES ||
      "sports,crypto,economy,politics,technology,entertainment,other"
    )
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
    maxAnalysisPerCategory: num(env.MAX_ANALYSIS_PER_CATEGORY, 2),
    discoveryBudgetFraction: num(env.DISCOVERY_BUDGET_FRACTION, 0.4),

    minLiquidity: num(env.MIN_LIQUIDITY, 10000),
    minVolume: num(env.MIN_VOLUME, 25000),
    maxSpread: num(env.MAX_SPREAD, 0.03),
    minPrice: num(env.MIN_PRICE, 0.15),
    maxPrice: num(env.MAX_PRICE, 0.85),
    minHoursToClose: num(env.MIN_HOURS_TO_CLOSE, 12),
    maxHoursToClose: num(env.MAX_HOURS_TO_CLOSE, 336),
    minNetEdge: num(env.MIN_NET_EDGE, 0.1),
    minEdgeCostMultiple: num(env.MIN_EDGE_COST_MULTIPLE, 2.5),
    minConfidence: num(env.MIN_CONFIDENCE, 0.65),
    maxCriticRisk: num(env.MAX_CRITIC_RISK, 0.45),

    bankrollUsdc: num(env.BANKROLL_USDC, 1000),
    kellyFraction: num(env.KELLY_FRACTION, 0.1),
    maxPositionPct: num(env.MAX_POSITION_PCT, 0.02),
    maxTotalExposurePct: num(env.MAX_TOTAL_EXPOSURE_PCT, 0.1),
    maxEventExposurePct: num(env.MAX_EVENT_EXPOSURE_PCT, 0.02),
    maxCategoryExposurePct: num(env.MAX_CATEGORY_EXPOSURE_PCT, 0.04),
    maxRelatedPositions: num(env.MAX_RELATED_POSITIONS, 1),
    maxNewPositionsPerDay: num(env.MAX_NEW_POSITIONS_PER_DAY, 1),
    dailyLossLimitPct: num(env.DAILY_LOSS_LIMIT_PCT, 0.01),
    pauseDrawdownPct: num(env.PAUSE_DRAWDOWN_PCT, 0.05),

    slippageBuffer: num(env.SLIPPAGE_BUFFER, 0.005),
    paperExecutionSlippagePct: num(env.PAPER_EXECUTION_SLIPPAGE_PCT, 0.0025),
    paperFeePct: num(env.PAPER_FEE_PCT, 0.001),
    maxAiCallsPerCycle: num(env.MAX_AI_CALLS_PER_CYCLE, 14),

    takeProfitPct: num(env.TAKE_PROFIT_PCT, 0.2),
    stopLossPct: num(env.STOP_LOSS_PCT, 0.2),
    trailingStopPct: num(env.TRAILING_STOP_PCT, 0.12),
    trailingActivationPct: num(env.TRAILING_ACTIVATION_PCT, 0.15),
    edgeExitEnabled: bool(env.EDGE_EXIT_ENABLED, false),
    exitMinEdge: num(env.EXIT_MIN_EDGE, 0.0),
    exitConfirmationCycles: num(env.EXIT_CONFIRMATION_CYCLES, 4),
    entryConfirmationCycles: num(env.ENTRY_CONFIRMATION_CYCLES, 3),
    entryConfirmationExpiryMinutes: num(env.ENTRY_CONFIRMATION_EXPIRY_MINUTES, 240),
    exitHoursToResolution: num(env.EXIT_HOURS_TO_RESOLUTION, 6),
    maxPositionAgeDays: num(env.MAX_POSITION_AGE_DAYS, 21),
    reopenCooldownDays: num(env.REOPEN_COOLDOWN_DAYS, 30),

    circuitBreakerFailures: num(env.CIRCUIT_BREAKER_FAILURES, 3),
    circuitBreakerCooldownMinutes: num(env.CIRCUIT_BREAKER_COOLDOWN_MINUTES, 60),
    snapshotRetentionDays: num(env.SNAPSHOT_RETENTION_DAYS, 90),
    ledgerRetentionDays: num(env.LEDGER_RETENTION_DAYS, 365),
    maintenanceMinIntervalHours: num(env.MAINTENANCE_MIN_INTERVAL_HOURS, 20),
    strategyVersion: env.STRATEGY_VERSION || "V6",
    campaignId: env.CAMPAIGN_ID || "paper-2026-v6-cf",

    telegramBotToken: env.TELEGRAM_BOT_TOKEN,
    telegramChatId: env.TELEGRAM_CHAT_ID,

    dashboardRefreshSeconds: num(env.DASHBOARD_REFRESH_SECONDS, 30),
    staleCycleMinutes: num(env.STALE_CYCLE_MINUTES, 30),
    dashboardUsername: env.DASHBOARD_USERNAME,
    dashboardPassword: env.DASHBOARD_PASSWORD,
  };
}
