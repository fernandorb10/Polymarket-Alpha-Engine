import type { Settings } from "./config";
import * as db from "./db";
import type { Env, Opportunity } from "./types";

export async function ledger(
  env: Env,
  settings: Settings,
  action: string,
  reason = "",
  opts: {
    cycleId?: number | null;
    marketId?: string | null;
    positionId?: number | null;
    payload?: unknown;
  } = {},
): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO decision_ledger(
      created_at,cycle_id,market_id,position_id,action,reason,strategy_version,campaign_id,payload_json
    ) VALUES(?,?,?,?,?,?,?,?,?)`,
  )
    .bind(
      db.now(),
      opts.cycleId ?? null,
      opts.marketId ?? null,
      opts.positionId ?? null,
      action,
      reason,
      settings.strategyVersion,
      settings.campaignId,
      JSON.stringify(opts.payload ?? {}),
    )
    .run();
}

export async function componentSuccess(env: Env, component: string): Promise<void> {
  await env.DB.prepare(
    `INSERT INTO service_health(component,consecutive_failures,last_success_at,last_error,paused_until)
     VALUES(?,0,?,NULL,NULL)
     ON CONFLICT(component) DO UPDATE SET
       consecutive_failures=0,last_success_at=excluded.last_success_at,last_error=NULL,paused_until=NULL`,
  )
    .bind(component, db.now())
    .run();
}

export async function componentFailure(
  env: Env,
  settings: Settings,
  component: string,
  error: unknown,
): Promise<number> {
  const row = await env.DB.prepare(
    "SELECT consecutive_failures FROM service_health WHERE component=?",
  )
    .bind(component)
    .first<{ consecutive_failures: number }>();
  const count = row ? Number(row.consecutive_failures) + 1 : 1;
  const paused =
    count >= settings.circuitBreakerFailures
      ? new Date(Date.now() + settings.circuitBreakerCooldownMinutes * 60000).toISOString()
      : null;
  await env.DB.prepare(
    `INSERT INTO service_health(component,consecutive_failures,last_failure_at,last_error,paused_until)
     VALUES(?,?,?,?,?)
     ON CONFLICT(component) DO UPDATE SET
       consecutive_failures=excluded.consecutive_failures,last_failure_at=excluded.last_failure_at,
       last_error=excluded.last_error,paused_until=excluded.paused_until`,
  )
    .bind(component, count, db.now(), String(error).slice(0, 1000), paused)
    .run();
  return count;
}

export async function componentAvailable(env: Env, component: string): Promise<boolean> {
  const row = await env.DB.prepare("SELECT paused_until FROM service_health WHERE component=?")
    .bind(component)
    .first<{ paused_until: string | null }>();
  if (!row || !row.paused_until) return true;
  const pausedUntil = new Date(row.paused_until).getTime();
  return Number.isNaN(pausedUntil) || pausedUntil <= Date.now();
}

function startOfDayIso(): string {
  const day = new Date();
  day.setUTCHours(0, 0, 0, 0);
  return day.toISOString();
}

export async function drawdownPauseReason(env: Env, settings: Settings): Promise<string | null> {
  const row = await env.DB.prepare(
    `SELECT MAX(equity) peak, (SELECT equity FROM equity_history ORDER BY id DESC LIMIT 1) current
     FROM equity_history`,
  ).first<{ peak: number | null; current: number | null }>();
  const dayPnl = await env.DB.prepare(
    "SELECT COALESCE(SUM(pnl_usdc),0) pnl FROM positions WHERE status='CLOSED' AND closed_at>=?",
  )
    .bind(startOfDayIso())
    .first<{ pnl: number }>();

  if (row && row.peak && row.current !== null) {
    const drawdown = (Number(row.peak) - Number(row.current)) / Number(row.peak);
    if (drawdown >= settings.pauseDrawdownPct) {
      return `DRAWDOWN_PAUSE:${(drawdown * 100).toFixed(2)}%`;
    }
  }
  const pnl = Number(dayPnl?.pnl ?? 0);
  if (pnl <= -(settings.bankrollUsdc * settings.dailyLossLimitPct)) {
    return `DAILY_LOSS_PAUSE:${pnl.toFixed(2)}`;
  }
  return null;
}

export async function openingsToday(env: Env, settings: Settings): Promise<number> {
  const row = await env.DB.prepare(
    "SELECT COUNT(*) n FROM positions WHERE opened_at>=? AND campaign_id=?",
  )
    .bind(startOfDayIso(), settings.campaignId)
    .first<{ n: number }>();
  return Number(row?.n ?? 0);
}

export async function reopenBlockReason(
  env: Env,
  settings: Settings,
  marketId: string,
): Promise<string | null> {
  const cutoff = new Date(Date.now() - settings.reopenCooldownDays * 86400000).toISOString();
  const row = await env.DB.prepare(
    `SELECT closed_at FROM positions
     WHERE market_id=? AND status='CLOSED' AND closed_at>=?
     ORDER BY closed_at DESC LIMIT 1`,
  )
    .bind(marketId, cutoff)
    .first<{ closed_at: string }>();
  return row ? `REOPEN_COOLDOWN:${row.closed_at}` : null;
}

export async function confirmEntry(
  env: Env,
  settings: Settings,
  opportunity: Opportunity,
): Promise<[boolean, number]> {
  const marketId = String(opportunity.market.id);
  const side = opportunity.side;
  const stamp = db.now();
  const cutoff = new Date(Date.now() - settings.entryConfirmationExpiryMinutes * 60000);

  const row = await env.DB.prepare("SELECT * FROM entry_confirmations WHERE market_id=?")
    .bind(marketId)
    .first<Record<string, unknown>>();

  let valid = false;
  if (row && row.side === side) {
    const lastSeen = new Date(String(row.last_seen_at));
    valid = !Number.isNaN(lastSeen.getTime()) && lastSeen >= cutoff;
  }
  const confirmations = valid ? Number(row!.confirmations) + 1 : 1;
  const firstSeen = valid ? String(row!.first_seen_at) : stamp;

  await env.DB.prepare(
    `INSERT OR REPLACE INTO entry_confirmations(
      market_id,side,confirmations,first_seen_at,last_seen_at,last_edge,last_confidence,payload_json
    ) VALUES(?,?,?,?,?,?,?,?)`,
  )
    .bind(
      marketId,
      side,
      confirmations,
      firstSeen,
      stamp,
      opportunity.netEdge,
      opportunity.confidence,
      JSON.stringify(opportunity),
    )
    .run();

  return [confirmations >= settings.entryConfirmationCycles, confirmations];
}

export async function clearEntryConfirmation(env: Env, marketId: string): Promise<void> {
  await env.DB.prepare("DELETE FROM entry_confirmations WHERE market_id=?").bind(marketId).run();
}

export async function canOpen(
  env: Env,
  settings: Settings,
  opportunity: Opportunity,
): Promise<[boolean, string, number]> {
  if (opportunity.decision !== "OPEN") return [false, `DECISION_${opportunity.decision}`, 0];

  const pause = await drawdownPauseReason(env, settings);
  if (pause) return [false, pause, 0];

  if ((await openingsToday(env, settings)) >= settings.maxNewPositionsPerDay) {
    return [false, "DAILY_OPEN_LIMIT", 0];
  }

  const cooldown = await reopenBlockReason(env, settings, String(opportunity.market.id));
  if (cooldown) return [false, cooldown, 0];

  const [confirmed, count] = await confirmEntry(env, settings, opportunity);
  if (!confirmed) {
    return [false, `ENTRY_CONFIRMATION:${count}/${settings.entryConfirmationCycles}`, count];
  }
  return [true, "ENTRY_CONFIRMED", count];
}

export async function tagOpenPosition(
  env: Env,
  settings: Settings,
  marketId: string,
  reason: string,
): Promise<number | null> {
  const row = await env.DB.prepare(
    "SELECT id FROM positions WHERE market_id=? AND status='OPEN' ORDER BY id DESC LIMIT 1",
  )
    .bind(marketId)
    .first<{ id: number }>();
  if (!row) return null;
  await env.DB.prepare(
    "UPDATE positions SET strategy_version=?,campaign_id=?,entry_reason=? WHERE id=?",
  )
    .bind(settings.strategyVersion, settings.campaignId, reason, row.id)
    .run();
  return Number(row.id);
}

export async function updateExcursions(env: Env): Promise<void> {
  const { results } = await env.DB.prepare("SELECT * FROM positions WHERE status='OPEN'").all();
  for (const row of results as Record<string, unknown>[]) {
    const mark = Number(row.last_price ?? row.entry_price);
    const value = Number(row.shares) * mark;
    const stake = Number(row.stake_usdc);
    const pnlPct = stake ? (value - stake) / stake : 0;
    await env.DB.prepare(
      "UPDATE positions SET mfe_pct=?,mae_pct=?,peak_value_usdc=?,trough_value_usdc=? WHERE id=?",
    )
      .bind(
        Math.max(Number(row.mfe_pct ?? 0), pnlPct),
        Math.min(Number(row.mae_pct ?? 0), pnlPct),
        Math.max(Number(row.peak_value_usdc ?? value), value),
        Math.min(Number(row.trough_value_usdc ?? value), value),
        row.id,
      )
      .run();
  }
}

export async function recordEquity(env: Env, settings: Settings): Promise<db.Summary> {
  const s = await db.summary(env, settings);
  await env.DB.prepare(
    `INSERT INTO equity_history(
      captured_at,equity,total_pnl,realized_pnl,unrealized_pnl,exposure,open_positions
    ) VALUES(?,?,?,?,?,?,?)`,
  )
    .bind(db.now(), s.equity, s.totalPnl, s.realizedPnl, s.unrealizedPnl, s.openStake, s.openPositions)
    .run();
  return s;
}

export async function ensureCampaign(env: Env, settings: Settings): Promise<void> {
  await env.DB.prepare(
    "INSERT OR IGNORE INTO campaigns(id,started_at,strategy_version,notes) VALUES(?,?,?,?)",
  )
    .bind(settings.campaignId, db.now(), settings.strategyVersion, "Cloudflare Workers paper-trading campaign")
    .run();
}

export async function dailyMaintenance(env: Env, settings: Settings): Promise<{
  skipped: boolean;
  snapshotsDeleted: number;
  ledgerDeleted: number;
}> {
  const cutoff = new Date(Date.now() - settings.maintenanceMinIntervalHours * 3600000).toISOString();
  const last = await env.DB.prepare("SELECT last_run_at FROM maintenance_runs WHERE name='daily'").first<{
    last_run_at: string;
  }>();
  if (last && last.last_run_at > cutoff) {
    return { skipped: true, snapshotsDeleted: 0, ledgerDeleted: 0 };
  }

  const snapshotsResult = await env.DB.prepare("DELETE FROM snapshots WHERE captured_at<?")
    .bind(new Date(Date.now() - settings.snapshotRetentionDays * 86400000).toISOString())
    .run();
  const ledgerResult = await env.DB.prepare("DELETE FROM decision_ledger WHERE created_at<?")
    .bind(new Date(Date.now() - settings.ledgerRetentionDays * 86400000).toISOString())
    .run();

  const result = {
    skipped: false,
    snapshotsDeleted: snapshotsResult.meta.changes ?? 0,
    ledgerDeleted: ledgerResult.meta.changes ?? 0,
  };
  await env.DB.prepare(
    "INSERT OR REPLACE INTO maintenance_runs(name,last_run_at,payload_json) VALUES('daily',?,?)",
  )
    .bind(db.now(), JSON.stringify(result))
    .run();
  return result;
}
