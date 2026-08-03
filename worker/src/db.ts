import type { Settings } from "./config";
import { classifyQuestion } from "./taxonomy";
import type { Env, Market, Opportunity, Side } from "./types";

export function now(): string {
  return new Date().toISOString();
}

// --- Paper execution pricing (mirrors alpha_engine/db.py) ---

export function executableEntryPrice(market: Market, side: Side): number {
  if (side === "YES") {
    if (market.bestAskYes !== null) return market.bestAskYes;
    return market.yesPrice + market.spread / 2;
  }
  if (market.bestBidYes !== null) return 1 - market.bestBidYes;
  return market.noPrice + market.spread / 2;
}

export function executableExitPrice(market: Market, side: Side): number {
  if (side === "YES") {
    if (market.bestBidYes !== null) return market.bestBidYes;
    return market.yesPrice - market.spread / 2;
  }
  if (market.bestAskYes !== null) return 1 - market.bestAskYes;
  return market.noPrice - market.spread / 2;
}

function buyPrice(price: number, settings: Settings): number {
  return Math.min(0.999, Math.max(0.001, price * (1 + settings.paperExecutionSlippagePct)));
}

function sellPrice(price: number, settings: Settings): number {
  return Math.min(0.999, Math.max(0.001, price * (1 - settings.paperExecutionSlippagePct)));
}

// --- Snapshots / analyses / cycles ---

export async function saveSnapshots(env: Env, markets: Market[]): Promise<void> {
  if (markets.length === 0) return;
  const stamp = now();
  const stmt = env.DB.prepare(
    `INSERT INTO snapshots(market_id,captured_at,question,yes_price,no_price,bid,ask,
      spread,liquidity,volume,volume_24h,rank_score,raw_json)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`,
  );
  const batch = markets.map((market) =>
    stmt.bind(
      market.id,
      stamp,
      market.question,
      market.yesPrice,
      market.noPrice,
      market.bestBidYes,
      market.bestAskYes,
      market.spread,
      market.liquidity,
      market.volume,
      market.volume24h,
      market.rankScore,
      JSON.stringify(market),
    ),
  );
  await env.DB.batch(batch);
}

export async function saveAnalysis(env: Env, opportunity: Opportunity): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO analyses(market_id,created_at,side,fair_probability,market_probability,
      gross_edge,net_edge,confidence,critic_risk,score,stake_usdc,decision,payload_json)
     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`,
  )
    .bind(
      opportunity.market.id,
      now(),
      opportunity.side,
      opportunity.fairProbability,
      opportunity.marketProbability,
      opportunity.grossEdge,
      opportunity.netEdge,
      opportunity.confidence,
      opportunity.criticRisk,
      opportunity.score,
      opportunity.stakeUsdc,
      opportunity.decision,
      JSON.stringify(opportunity),
    )
    .run();
}

export async function startCycle(env: Env): Promise<number> {
  const result = await env.DB.prepare("INSERT INTO cycles(started_at) VALUES(?)")
    .bind(now())
    .run();
  return Number(result.meta.last_row_id);
}

export async function finishCycle(
  env: Env,
  cycleId: number,
  seen: number,
  eligibleCount: number,
  analysed: number,
  opened: number,
  error?: string,
): Promise<void> {
  await env.DB.prepare(
    `UPDATE cycles SET finished_at=?,markets_seen=?,eligible=?,analysed=?,opened=?,error=?
     WHERE id=?`,
  )
    .bind(now(), seen, eligibleCount, analysed, opened, error ?? null, cycleId)
    .run();
}

export async function recentCycles(env: Env, limit = 20): Promise<Record<string, unknown>[]> {
  const { results } = await env.DB.prepare("SELECT * FROM cycles ORDER BY id DESC LIMIT ?")
    .bind(limit)
    .all();
  return results as Record<string, unknown>[];
}

export async function latestCycle(env: Env): Promise<Record<string, unknown> | null> {
  const rows = await recentCycles(env, 1);
  return rows[0] ?? null;
}

export async function recentAnalyses(env: Env, limit = 50): Promise<Record<string, unknown>[]> {
  const { results } = await env.DB.prepare(
    "SELECT * FROM analyses ORDER BY created_at DESC LIMIT ?",
  )
    .bind(limit)
    .all();
  return results as Record<string, unknown>[];
}

// --- Market selection support ---

export async function openMarketIds(env: Env): Promise<Set<string>> {
  const { results } = await env.DB.prepare(
    "SELECT market_id FROM positions WHERE status='OPEN'",
  ).all();
  return new Set(results.map((row) => String((row as Record<string, unknown>).market_id)));
}

export async function openMarketIdsByOldestAnalysis(env: Env): Promise<string[]> {
  const { results } = await env.DB.prepare(
    `SELECT p.market_id, MAX(a.created_at) AS last_analysis
     FROM positions p
     LEFT JOIN analyses a ON a.market_id=p.market_id
     WHERE p.status='OPEN'
     GROUP BY p.market_id
     ORDER BY last_analysis IS NOT NULL, last_analysis, p.opened_at`,
  ).all();
  return results.map((row) => String((row as Record<string, unknown>).market_id));
}

export async function recentlyAnalyzedMarketIds(env: Env, minutes: number): Promise<Set<string>> {
  const cutoff = new Date(Date.now() - minutes * 60000).toISOString();
  const { results } = await env.DB.prepare(
    "SELECT DISTINCT market_id FROM analyses WHERE created_at>=?",
  )
    .bind(cutoff)
    .all();
  return new Set(results.map((row) => String((row as Record<string, unknown>).market_id)));
}

// --- Exposure / portfolio limits ---

export async function exposure(env: Env): Promise<number> {
  const row = await env.DB.prepare(
    "SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN'",
  ).first<{ v: number }>();
  return Number(row?.v ?? 0);
}

interface PortfolioUsage {
  category: string;
  eventKey: string;
  total: number;
  categoryStake: number;
  eventStake: number;
  related: number;
}

async function portfolioUsage(env: Env, question: string, rawCategory = ""): Promise<PortfolioUsage> {
  const [category, key] = classifyQuestion(question, rawCategory);
  const total = await env.DB.prepare(
    "SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN'",
  ).first<{ v: number }>();
  const categoryStake = await env.DB.prepare(
    "SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN' AND category=?",
  )
    .bind(category)
    .first<{ v: number }>();
  const eventStake = await env.DB.prepare(
    "SELECT COALESCE(SUM(stake_usdc),0) v FROM positions WHERE status='OPEN' AND event_key=?",
  )
    .bind(key)
    .first<{ v: number }>();
  const related = await env.DB.prepare(
    "SELECT COUNT(*) n FROM positions WHERE status='OPEN' AND event_key=?",
  )
    .bind(key)
    .first<{ n: number }>();

  return {
    category,
    eventKey: key,
    total: Number(total?.v ?? 0),
    categoryStake: Number(categoryStake?.v ?? 0),
    eventStake: Number(eventStake?.v ?? 0),
    related: Number(related?.n ?? 0),
  };
}

export async function maxAllowedStake(
  env: Env,
  settings: Settings,
  question: string,
  rawCategory = "",
): Promise<[number, string | null]> {
  const usage = await portfolioUsage(env, question, rawCategory);
  if (usage.related >= settings.maxRelatedPositions) return [0, "RELATED_LIMIT"];

  const rooms: [string, number][] = [
    ["TOTAL_EXPOSURE_LIMIT", settings.bankrollUsdc * settings.maxTotalExposurePct - usage.total],
    [
      "CATEGORY_LIMIT",
      settings.bankrollUsdc * settings.maxCategoryExposurePct - usage.categoryStake,
    ],
    ["EVENT_LIMIT", settings.bankrollUsdc * settings.maxEventExposurePct - usage.eventStake],
  ];
  rooms.sort((a, b) => a[1] - b[1]);
  const [limitingReason, room] = rooms[0];
  return [Math.max(0, room), limitingReason];
}

export async function portfolioAllows(
  env: Env,
  settings: Settings,
  question: string,
  stake: number,
  rawCategory = "",
): Promise<[boolean, string | null]> {
  const [room, reason] = await maxAllowedStake(env, settings, question, rawCategory);
  if (room + 1e-9 < stake) return [false, reason || "PORTFOLIO_LIMIT"];
  return [true, null];
}

// --- Positions lifecycle ---

export async function openPosition(
  env: Env,
  settings: Settings,
  opportunity: Opportunity,
): Promise<boolean> {
  if (opportunity.decision !== "OPEN") return false;

  const [room] = await maxAllowedStake(
    env,
    settings,
    opportunity.market.question,
    opportunity.market.category,
  );
  const stake = Math.round(Math.min(opportunity.stakeUsdc, room) * 100) / 100;
  if (stake < 1) return false;
  opportunity.stakeUsdc = stake;

  const token =
    opportunity.side === "YES" ? opportunity.market.yesTokenId : opportunity.market.noTokenId;
  const [category, key] = classifyQuestion(
    opportunity.market.question,
    opportunity.market.category,
  );
  const entryPrice = buyPrice(executableEntryPrice(opportunity.market, opportunity.side), settings);
  const fee = stake * settings.paperFeePct;
  const shares = entryPrice ? Math.max(0, stake - fee) / entryPrice : 0;

  try {
    await env.DB.prepare(
      `INSERT INTO positions(
        market_id,token_id,question,side,entry_price,shares,stake_usdc,opened_at,
        last_price,last_marked_at,category,event_key,peak_price,edge_gone_count,entry_fee_usdc
      ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    )
      .bind(
        opportunity.market.id,
        token,
        opportunity.market.question,
        opportunity.side,
        entryPrice,
        shares,
        stake,
        now(),
        entryPrice,
        now(),
        category,
        key,
        entryPrice,
        0,
        fee,
      )
      .run();
    return true;
  } catch {
    // Unique index on (market_id) WHERE status='OPEN' rejects a duplicate open position.
    return false;
  }
}

export async function markPositions(env: Env, markets: Market[]): Promise<number> {
  const byId = new Map(markets.map((market) => [market.id, market]));
  const { results } = await env.DB.prepare("SELECT * FROM positions WHERE status='OPEN'").all();
  const stamp = now();
  let marked = 0;
  for (const row of results as Record<string, unknown>[]) {
    const market = byId.get(String(row.market_id));
    if (!market) continue;
    const price = executableExitPrice(market, row.side as Side);
    const peak = Math.max(Number(row.peak_price ?? row.entry_price), price);
    await env.DB.prepare(
      "UPDATE positions SET last_price=?,last_marked_at=?,peak_price=? WHERE id=?",
    )
      .bind(price, stamp, peak, row.id)
      .run();
    marked += 1;
  }
  return marked;
}

interface CloseResult {
  exitPrice: number;
  pnlUsdc: number;
}

async function closePositionRow(
  env: Env,
  settings: Settings,
  position: Record<string, unknown>,
  marketPrice: number,
  reason: string,
): Promise<CloseResult> {
  const exitPrice = sellPrice(marketPrice, settings);
  const gross = Number(position.shares) * exitPrice;
  const exitFee = gross * settings.paperFeePct;
  const pnl = gross - exitFee - Number(position.stake_usdc);
  const stamp = now();
  await env.DB.prepare(
    `UPDATE positions
     SET status='CLOSED',exit_price=?,closed_at=?,pnl_usdc=?,resolution=?,
         last_price=?,last_marked_at=?,exit_fee_usdc=?,close_detail_json=?
     WHERE id=? AND status='OPEN'`,
  )
    .bind(
      exitPrice,
      stamp,
      pnl,
      reason,
      marketPrice,
      stamp,
      exitFee,
      JSON.stringify({ gross_value: gross, exit_fee: exitFee, reason }),
      position.id,
    )
    .run();
  return { exitPrice, pnlUsdc: pnl };
}

export interface ClosedPosition {
  id: number;
  question: string;
  reason: string;
  pnlPct: number;
  exitPrice: number;
  pnlUsdc: number;
}

export async function manageExits(
  env: Env,
  settings: Settings,
  markets: Market[],
  opportunities: Opportunity[],
): Promise<ClosedPosition[]> {
  const marketById = new Map(markets.map((market) => [market.id, market]));
  const opportunityById = new Map(
    opportunities.map((opportunity) => [opportunity.market.id, opportunity]),
  );
  const closed: ClosedPosition[] = [];
  const current = Date.now();

  const { results } = await env.DB.prepare("SELECT * FROM positions WHERE status='OPEN'").all();

  for (const position of results as Record<string, unknown>[]) {
    const market = marketById.get(String(position.market_id));
    if (!market) continue;

    const executable = executableExitPrice(market, position.side as Side);
    const estimate = sellPrice(executable, settings);
    const exitFee = Number(position.shares) * estimate * settings.paperFeePct;
    const pnl = Number(position.shares) * estimate - exitFee - Number(position.stake_usdc);
    const stake = Number(position.stake_usdc);
    const pnlPct = stake ? pnl / stake : 0;
    const peak = Math.max(Number(position.peak_price ?? position.entry_price), executable);
    const trailing = peak ? (peak - executable) / peak : 0;
    let reason: string | null = null;

    if (pnlPct >= settings.takeProfitPct) {
      reason = "TAKE_PROFIT";
    } else if (pnlPct <= -settings.stopLossPct) {
      reason = "STOP_LOSS";
    } else if (
      peak >= Number(position.entry_price) * (1 + settings.trailingActivationPct) &&
      trailing >= settings.trailingStopPct
    ) {
      reason = "TRAILING_STOP";
    } else {
      const openedAt = new Date(String(position.opened_at)).getTime();
      const ageDays = (current - openedAt) / 86400000;
      if (ageDays >= settings.maxPositionAgeDays) {
        reason = "MAX_AGE";
      } else if (market.endDate) {
        const hoursLeftToEnd = (new Date(market.endDate).getTime() - current) / 3600000;
        if (hoursLeftToEnd <= settings.exitHoursToResolution) reason = "NEAR_RESOLUTION";
      }
    }

    const opportunity = opportunityById.get(String(position.market_id));
    const edgeBad =
      settings.edgeExitEnabled &&
      opportunity !== undefined &&
      (opportunity.side !== position.side ||
        opportunity.netEdge < settings.exitMinEdge ||
        opportunity.criticRisk > settings.maxCriticRisk ||
        opportunity.criticReport.recommendation === "REJECT");

    let count = Number(position.edge_gone_count ?? 0);
    if (edgeBad) {
      count += 1;
    } else if (opportunity !== undefined) {
      count = 0;
    }

    await env.DB.prepare("UPDATE positions SET edge_gone_count=? WHERE id=?")
      .bind(count, position.id)
      .run();

    if (reason === null && count >= settings.exitConfirmationCycles) {
      reason = "EDGE_GONE_CONFIRMED";
    }

    if (reason) {
      const result = await closePositionRow(env, settings, position, executable, reason);
      closed.push({
        id: Number(position.id),
        question: String(position.question),
        reason,
        pnlPct,
        exitPrice: result.exitPrice,
        pnlUsdc: result.pnlUsdc,
      });
    }
  }

  return closed;
}

export async function listPositions(
  env: Env,
  openOnly = false,
): Promise<Record<string, unknown>[]> {
  const query =
    "SELECT *, (shares*COALESCE(last_price,entry_price)-stake_usdc) unrealized_pnl FROM positions" +
    (openOnly ? " WHERE status='OPEN'" : "") +
    " ORDER BY opened_at DESC";
  const { results } = await env.DB.prepare(query).all();
  return results as Record<string, unknown>[];
}

export interface Summary {
  openPositions: number;
  openStake: number;
  exposurePct: number;
  unrealizedPnl: number;
  closedPositions: number;
  realizedPnl: number;
  totalPnl: number;
  equity: number;
  returnPct: number;
  wins: number;
  losses: number;
  winRate: number;
  profitFactor: number | null;
}

export async function summary(env: Env, settings: Settings): Promise<Summary> {
  const openRow = await env.DB.prepare(
    `SELECT COUNT(*) n, COALESCE(SUM(stake_usdc),0) stake,
            COALESCE(SUM(shares*COALESCE(last_price,entry_price)-stake_usdc),0) upnl
     FROM positions WHERE status='OPEN'`,
  ).first<{ n: number; stake: number; upnl: number }>();
  const closedRow = await env.DB.prepare(
    `SELECT COUNT(*) n, COALESCE(SUM(pnl_usdc),0) pnl,
            COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END),0) wins,
            COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN 1 ELSE 0 END),0) losses,
            COALESCE(SUM(CASE WHEN pnl_usdc>0 THEN pnl_usdc ELSE 0 END),0) gp,
            ABS(COALESCE(SUM(CASE WHEN pnl_usdc<0 THEN pnl_usdc ELSE 0 END),0)) gl
     FROM positions WHERE status='CLOSED'`,
  ).first<{ n: number; pnl: number; wins: number; losses: number; gp: number; gl: number }>();

  const open = openRow ?? { n: 0, stake: 0, upnl: 0 };
  const closedData = closedRow ?? { n: 0, pnl: 0, wins: 0, losses: 0, gp: 0, gl: 0 };
  const total = Number(open.upnl) + Number(closedData.pnl);
  const closedCount = Number(closedData.n);
  const grossLoss = Number(closedData.gl);

  return {
    openPositions: Number(open.n),
    openStake: Number(open.stake),
    exposurePct: Number(open.stake) / settings.bankrollUsdc,
    unrealizedPnl: Number(open.upnl),
    closedPositions: closedCount,
    realizedPnl: Number(closedData.pnl),
    totalPnl: total,
    equity: settings.bankrollUsdc + total,
    returnPct: total / settings.bankrollUsdc,
    wins: Number(closedData.wins),
    losses: Number(closedData.losses),
    winRate: closedCount ? Number(closedData.wins) / closedCount : 0,
    profitFactor: grossLoss ? Number(closedData.gp) / grossLoss : null,
  };
}

export async function categoryExposure(env: Env): Promise<Record<string, unknown>[]> {
  const { results } = await env.DB.prepare(
    `SELECT COALESCE(category,'other') category, COUNT(*) positions, SUM(stake_usdc) stake
     FROM positions WHERE status='OPEN' GROUP BY category ORDER BY stake DESC`,
  ).all();
  return results as Record<string, unknown>[];
}
