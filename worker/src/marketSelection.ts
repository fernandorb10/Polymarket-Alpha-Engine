import type { Settings } from "./config";
import { classifyMarket } from "./taxonomy";
import type { Market } from "./types";

export function marketCategory(market: Market): string {
  return classifyMarket(market.question, market.category);
}

export function categoryCounts(markets: Market[]): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const market of markets) {
    const category = marketCategory(market);
    counts[category] = (counts[category] ?? 0) + 1;
  }
  return Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)));
}

export function selectBalanced(
  settings: Settings,
  ranked: Market[],
  limit: number,
  openIds: string[],
  recentIds: Set<string>,
  diversityRecentIds: Set<string> = new Set(),
  pendingConfirmationIds: Set<string> = new Set(),
): Market[] {
  const selected: Market[] = [];
  const selectedIds = new Set<string>();
  const counts: Record<string, number> = {};

  const rankedById = new Map(ranked.map((market) => [String(market.id), market]));

  const add = (market: Market): boolean => {
    const marketId = String(market.id);
    if (selectedIds.has(marketId)) return false;
    selected.push(market);
    selectedIds.add(marketId);
    const category = marketCategory(market);
    counts[category] = (counts[category] ?? 0) + 1;
    return true;
  };

  const discoverySlots = Math.max(1, Math.round(limit * settings.discoveryBudgetFraction));
  const managementSlots = Math.max(0, limit - discoverySlots);

  for (const marketId of openIds) {
    if (selected.length >= managementSlots) break;
    const market = rankedById.get(marketId);
    if (market) add(market);
  }

  for (const market of ranked) {
    if (selected.length >= managementSlots) break;
    if (pendingConfirmationIds.has(String(market.id))) add(market);
  }

  const globallyAvailable = ranked.filter(
    (market) => !selectedIds.has(String(market.id)) && !recentIds.has(String(market.id)),
  );
  const diversityAvailable = ranked.filter(
    (market) => !selectedIds.has(String(market.id)) && !diversityRecentIds.has(String(market.id)),
  );

  if (settings.diversifyAnalysis) {
    const buckets = new Map<string, Market[]>();
    for (const market of diversityAvailable) {
      const category = marketCategory(market);
      if (!buckets.has(category)) buckets.set(category, []);
      buckets.get(category)!.push(market);
    }

    for (const category of settings.analysisCategoryList) {
      if (selected.length >= limit) break;
      if ((counts[category] ?? 0) >= settings.maxAnalysisPerCategory) continue;
      for (const market of buckets.get(category) ?? []) {
        if (add(market)) break;
      }
    }
  }

  for (const market of globallyAvailable) {
    if (selected.length >= limit) break;
    const category = marketCategory(market);
    if (settings.diversifyAnalysis && (counts[category] ?? 0) >= settings.maxAnalysisPerCategory) {
      continue;
    }
    add(market);
  }

  for (const market of globallyAvailable) {
    if (selected.length >= limit) break;
    add(market);
  }

  return selected;
}
