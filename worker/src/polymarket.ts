import type { Settings } from "./config";
import type { Market } from "./types";

function toFloat(value: unknown, fallback = 0): number {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}

function toArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? parsed : [];
    } catch {
      return [];
    }
  }
  return [];
}

function toIso(value: unknown): string | null {
  if (!value) return null;
  const date = new Date(String(value));
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function parseMarket(data: Record<string, unknown>): Market {
  const outcomes = toArray(data.outcomes).map((o) => String(o).toLowerCase());
  const prices = toArray(data.outcomePrices).map((p) => toFloat(p));
  const tokens = toArray(data.clobTokenIds).map((t) => String(t));
  const yesIndex = outcomes.indexOf("yes") >= 0 ? outcomes.indexOf("yes") : 0;
  const noIndex = outcomes.indexOf("no") >= 0 ? outcomes.indexOf("no") : 1;
  const yesPrice = yesIndex < prices.length ? prices[yesIndex] : 0.5;
  const noPrice = noIndex < prices.length ? prices[noIndex] : 1 - yesPrice;

  return {
    id: String(data.id ?? data.conditionId ?? ""),
    conditionId: String(data.conditionId ?? ""),
    question: String(data.question ?? ""),
    slug: String(data.slug ?? ""),
    rules: String(data.description ?? ""),
    category: String(data.category ?? "unknown"),
    endDate: toIso(data.endDate),
    active: data.active === undefined ? true : Boolean(data.active),
    closed: Boolean(data.closed ?? false),
    yesTokenId: yesIndex < tokens.length ? tokens[yesIndex] : "",
    noTokenId: noIndex < tokens.length ? tokens[noIndex] : "",
    yesPrice,
    noPrice,
    bestBidYes: null,
    bestAskYes: null,
    spread: toFloat(data.spread),
    liquidity: toFloat(data.liquidityNum ?? data.liquidity),
    volume: toFloat(data.volumeNum ?? data.volume),
    volume24h: toFloat(data.volume24hr),
    rankScore: 0,
  };
}

export async function listActiveMarkets(settings: Settings): Promise<Market[]> {
  const rowsById = new Map<string, Record<string, unknown>>();
  let offset = 0;
  const pageSize = Math.min(100, settings.scanPageSize);

  while (rowsById.size < settings.scanLimit) {
    const requestLimit = Math.min(pageSize, settings.scanLimit - rowsById.size);
    const url = new URL(`${settings.gammaUrl}/markets`);
    url.searchParams.set("active", "true");
    url.searchParams.set("closed", "false");
    url.searchParams.set("limit", String(requestLimit));
    url.searchParams.set("offset", String(offset));

    const response = await fetch(url.toString(), {
      headers: { "User-Agent": "polymarket-alpha-engine-worker/1.0" },
      signal: AbortSignal.timeout(settings.httpTimeoutMs),
    });
    if (!response.ok) throw new Error(`Gamma markets request failed: ${response.status}`);
    const batch = (await response.json()) as unknown;
    if (!Array.isArray(batch) || batch.length === 0) break;

    const before = rowsById.size;
    for (const row of batch as Record<string, unknown>[]) {
      const marketId = String(row.id ?? row.conditionId ?? "");
      if (marketId && !rowsById.has(marketId)) rowsById.set(marketId, row);
    }
    if (rowsById.size === before) break;
    offset += batch.length;
  }

  const markets = Array.from(rowsById.values())
    .slice(0, settings.scanLimit)
    .map(parseMarket)
    .filter((market) => market.yesTokenId);
  return markets;
}

export async function enrichBooks(settings: Settings, markets: Market[]): Promise<void> {
  const tokenIds = markets.map((m) => m.yesTokenId).filter(Boolean);
  const byTokenId = new Map(markets.filter((m) => m.yesTokenId).map((m) => [m.yesTokenId, m]));

  for (let i = 0; i < tokenIds.length; i += 500) {
    const chunk = tokenIds.slice(i, i + 500);
    const response = await fetch(`${settings.clobUrl}/books`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(chunk.map((tokenId) => ({ token_id: tokenId }))),
      signal: AbortSignal.timeout(settings.httpTimeoutMs),
    });
    if (!response.ok) continue;
    const books = (await response.json()) as Record<string, unknown>[];
    for (const book of books) {
      const market = byTokenId.get(String(book.asset_id ?? ""));
      if (!market) continue;
      const bids = toArray(book.bids)
        .map((item) => toFloat((item as Record<string, unknown>).price))
        .sort((a, b) => b - a);
      const asks = toArray(book.asks)
        .map((item) => toFloat((item as Record<string, unknown>).price))
        .sort((a, b) => a - b);
      market.bestBidYes = bids.length ? bids[0] : null;
      market.bestAskYes = asks.length ? asks[0] : null;
      if (market.bestBidYes !== null && market.bestAskYes !== null) {
        market.spread = Math.max(0, market.bestAskYes - market.bestBidYes);
        market.yesPrice = (market.bestBidYes + market.bestAskYes) / 2;
        market.noPrice = 1 - market.yesPrice;
      }
    }
  }
}
