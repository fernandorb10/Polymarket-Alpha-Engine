import type { Settings } from "./config";
import type { CriticReport, Decision, Market, Opportunity, ProbabilityReport } from "./types";
import { executableEntryPrice } from "./db";

export function hoursLeft(market: Market): number {
  if (!market.endDate) return Infinity;
  const end = new Date(market.endDate).getTime();
  return (end - Date.now()) / 3600000;
}

export function eligible(market: Market, settings: Settings): boolean {
  const remaining = hoursLeft(market);
  return (
    market.active &&
    !market.closed &&
    market.liquidity >= settings.minLiquidity &&
    market.volume >= settings.minVolume &&
    market.spread <= settings.maxSpread &&
    settings.minPrice <= market.yesPrice &&
    market.yesPrice <= settings.maxPrice &&
    settings.minHoursToClose <= remaining &&
    remaining <= settings.maxHoursToClose
  );
}

export function rankMarket(market: Market, settings: Settings): number {
  const liquidity = Math.min(1, Math.log10(Math.max(market.liquidity, 1)) / 6);
  const volume = Math.min(1, Math.log10(Math.max(market.volume, 1)) / 7);
  const activity = Math.min(1, Math.log10(Math.max(market.volume24h, 1)) / 5);
  const spreadScore = Math.max(0, 1 - market.spread / Math.max(settings.maxSpread, 0.001));

  const remaining = hoursLeft(market);
  const horizon = !isFinite(remaining)
    ? 0
    : Math.max(0, 1 - remaining / Math.max(settings.maxHoursToClose, 1));

  market.rankScore =
    100 * (0.3 * liquidity + 0.25 * volume + 0.2 * activity + 0.2 * spreadScore + 0.05 * horizon);
  return market.rankScore;
}

export function kellyBinary(probability: number, price: number): number {
  if (price <= 0 || price >= 1) return 0;
  const odds = (1 - price) / price;
  return Math.max(0, (odds * probability - (1 - probability)) / odds);
}

export function requiredEdge(market: Market, settings: Settings): number {
  const estimatedRoundTripCost =
    market.spread + 2 * settings.slippageBuffer + 2 * settings.paperFeePct;
  return Math.max(settings.minNetEdge, estimatedRoundTripCost * settings.minEdgeCostMultiple);
}

export function buildOpportunity(
  market: Market,
  probability: ProbabilityReport,
  critic: CriticReport,
  currentExposure: number,
  settings: Settings,
): Opportunity {
  const side = probability.probability_yes >= market.yesPrice ? "YES" : "NO";
  const fair = side === "YES" ? probability.probability_yes : 1 - probability.probability_yes;
  const executablePrice = executableEntryPrice(market, side);
  const grossEdge = fair - executablePrice;
  const netEdge = grossEdge - settings.slippageBuffer;
  const threshold = requiredEdge(market, settings);

  const kelly = kellyBinary(fair, executablePrice) * settings.kellyFraction;
  const maxStake = settings.bankrollUsdc * settings.maxPositionPct;
  const exposureRoom = Math.max(
    0,
    settings.bankrollUsdc * settings.maxTotalExposurePct - currentExposure,
  );
  const stake = Math.min(settings.bankrollUsdc * kelly, maxStake, exposureRoom);
  const expectedValue =
    executablePrice > 0
      ? (fair * (1 - executablePrice) - (1 - fair) * executablePrice) / executablePrice
      : -1;

  const evidenceSources = new Set(probability.source_urls).size;
  let decision: Decision = "OPEN";
  let reason = "V6 cost-aware thresholds passed";

  if (evidenceSources < settings.minEvidenceSources) {
    decision = "REJECT";
    reason = "insufficient independent evidence";
  } else if (netEdge < threshold) {
    decision = "REJECT";
    reason = `net edge ${netEdge.toFixed(3)} below cost-aware threshold ${threshold.toFixed(3)}`;
  } else if (probability.confidence < settings.minConfidence) {
    decision = "REJECT";
    reason = "forecast confidence below V6 threshold";
  } else if (critic.risk_score > settings.maxCriticRisk) {
    decision = "REJECT";
    reason = "critic risk above V6 threshold";
  } else if (critic.recommendation !== "ACCEPT") {
    decision = "REJECT";
    reason = `critic recommendation ${critic.recommendation}`;
  } else if (stake < 1) {
    decision = "REJECT";
    reason = "insufficient portfolio room";
  }

  const score = 100 * Math.max(0, netEdge - threshold) * probability.confidence * (1 - critic.risk_score);

  return {
    market,
    side,
    fairProbability: fair,
    marketProbability: executablePrice,
    grossEdge,
    netEdge,
    expectedValuePerDollar: expectedValue,
    confidence: probability.confidence,
    criticRisk: critic.risk_score,
    kellyFraction: kelly,
    stakeUsdc: Math.round(stake * 100) / 100,
    score,
    decision,
    reason,
    probabilityReport: probability,
    criticReport: critic,
  };
}
