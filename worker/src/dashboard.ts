import type { Settings } from "./config";
import * as db from "./db";
import type { Env } from "./types";

function escapeHtml(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

function money(value: unknown): string {
  const n = Number(value ?? 0);
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function pct(value: unknown): string {
  const n = Number(value ?? 0) * 100;
  return `${n.toFixed(1)}%`;
}

function dt(value: unknown): string {
  if (!value) return "-";
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 19);
  return `${date.toISOString().slice(0, 10).split("-").reverse().join("/")} ${date
    .toISOString()
    .slice(11, 19)} UTC`;
}

function payload(row: Record<string, unknown>): Record<string, unknown> {
  try {
    return JSON.parse(String(row.payload_json ?? "{}"));
  } catch {
    return {};
  }
}

export function requireAuth(request: Request, settings: Settings): Response | null {
  if (!settings.dashboardUsername || !settings.dashboardPassword) return null;
  const header = request.headers.get("Authorization") ?? "";
  const unauthorized = new Response("Autenticación requerida", {
    status: 401,
    headers: { "WWW-Authenticate": "Basic" },
  });
  if (!header.startsWith("Basic ")) return unauthorized;
  try {
    const [user, pass] = atob(header.slice(6)).split(":");
    if (user === settings.dashboardUsername && pass === settings.dashboardPassword) return null;
  } catch {
    // fall through to unauthorized
  }
  return unauthorized;
}

function engineStatus(latest: Record<string, unknown> | null, settings: Settings): [string, string] {
  if (!latest || !latest.finished_at) return ["DESCONOCIDO", "No hay ciclos completados"];
  const finished = new Date(String(latest.finished_at));
  if (Number.isNaN(finished.getTime())) return ["DESCONOCIDO", "Fecha del ciclo no válida"];
  const ageMinutes = (Date.now() - finished.getTime()) / 60000;
  if (latest.error) return ["ERROR", String(latest.error)];
  if (ageMinutes > settings.staleCycleMinutes) {
    return ["ATRASADO", `Último ciclo hace ${ageMinutes.toFixed(0)} minutos`];
  }
  return ["SALUDABLE", `Último ciclo hace ${ageMinutes.toFixed(0)} minutos`];
}

function svgLine(values: number[], width = 1000, height = 220, moneyLabels = false): string {
  if (values.length === 0) return "<div class='empty'>Aún no hay histórico suficiente.</div>";
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const span = hi - lo || 1;
  const points = values.map((value, index) => {
    const x = 12 + (index * (width - 24)) / Math.max(1, values.length - 1);
    const y = 12 + ((hi - value) * (height - 24)) / span;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const top = moneyLabels ? money(hi) : `${(hi * 100).toFixed(2)}%`;
  const bottom = moneyLabels ? money(lo) : `${(lo * 100).toFixed(2)}%`;
  return `<svg viewBox='0 0 ${width} ${height}' class='chart'><polyline points='${points.join(" ")}' fill='none' stroke='currentColor' stroke-width='3'/><text x='12' y='20'>${top}</text><text x='12' y='${height - 8}'>${bottom}</text></svg>`;
}

function page(title: string, body: string, refresh = false, refreshSeconds = 30): string {
  const refreshTag = refresh
    ? `<meta http-equiv='refresh' content='${refreshSeconds}'>`
    : "";
  return `<!doctype html><html lang='es'><head><meta charset='utf-8'>${refreshTag}<meta name='viewport' content='width=device-width,initial-scale=1'><title>${escapeHtml(title)}</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{font-family:Inter,Arial,sans-serif;background:#0b1020;color:#e8ecf3;margin:0}main{max-width:1700px;margin:auto;padding:28px}a{color:#7fb3ff;text-decoration:none}h1{margin:0 0 6px}h2{margin-top:30px}h3{margin-bottom:8px}.topbar{display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap;align-items:flex-start}.muted{color:#8792a8;font-size:12px;line-height:1.45;margin-top:4px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;margin:22px 0}.card,.panel,.status{background:#141b2d;border:1px solid #26314d;border-radius:12px;padding:17px}.label{color:#9aa5ba;font-size:12px;text-transform:uppercase;letter-spacing:.08em}.value{font-size:24px;font-weight:700;margin-top:7px}.table-wrap{overflow-x:auto;border:1px solid #26314d;border-radius:12px}table{border-collapse:collapse;width:100%;min-width:1000px;background:#11182a}th,td{padding:12px;border-bottom:1px solid #222d47;text-align:left;vertical-align:top}th{color:#9aa5ba;font-size:12px;text-transform:uppercase;background:#151d31;position:sticky;top:0}.badge{padding:4px 8px;border-radius:999px;background:#27385d;font-weight:700;font-size:12px}.positive{color:#54d69b}.negative{color:#ff7b8b}.warning{color:#f4c96b}.neutral{color:#c8d0df}.empty{padding:25px;color:#8792a8;background:#11182a;border:1px solid #26314d;border-radius:12px}.chart{width:100%;height:220px;color:#54d69b;background:#11182a;border-radius:12px}.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}.toolbar{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.button{display:inline-block;background:#27385d;color:#e8ecf3;padding:9px 13px;border-radius:8px}@media(max-width:720px){main{padding:16px}.value{font-size:20px}table{min-width:850px}}
</style></head><body><main>${body}</main></body></html>`;
}

export async function renderHome(env: Env, settings: Settings): Promise<string> {
  const [summary, allPositions, recentCycles] = await Promise.all([
    db.summary(env, settings),
    db.listPositions(env),
    db.recentCycles(env, 10),
  ]);
  const openPositions = allPositions.filter((p) => p.status === "OPEN");
  const closedPositions = allPositions.filter((p) => p.status === "CLOSED").slice(0, 20);
  const latestCycle = recentCycles[0] ?? null;
  const [state, detail] = engineStatus(latestCycle, settings);
  const stateClass = state === "SALUDABLE" ? "positive" : state === "ERROR" ? "negative" : "warning";

  const equityHistory = (
    await env.DB.prepare("SELECT * FROM equity_history ORDER BY id DESC LIMIT 200").all()
  ).results.reverse() as Record<string, unknown>[];

  const rejected = (
    await env.DB.prepare(
      "SELECT * FROM decision_ledger WHERE action='REJECT' ORDER BY id DESC LIMIT 15",
    ).all()
  ).results as Record<string, unknown>[];
  const decisions = (
    await env.DB.prepare("SELECT * FROM decision_ledger ORDER BY id DESC LIMIT 15").all()
  ).results as Record<string, unknown>[];
  const confirmations = (
    await env.DB.prepare("SELECT * FROM entry_confirmations ORDER BY last_seen_at DESC LIMIT 20").all()
  ).results as Record<string, unknown>[];
  const health = (
    await env.DB.prepare("SELECT * FROM service_health ORDER BY component").all()
  ).results as Record<string, unknown>[];
  const exposureRows = await db.categoryExposure(env);

  const openRows = openPositions
    .map((p) => {
      const mark = Number(p.last_price ?? p.entry_price);
      const pnl = Number(p.unrealized_pnl);
      const pnlClass = pnl > 0 ? "positive" : pnl < 0 ? "negative" : "neutral";
      return `<tr><td><strong>${escapeHtml(p.question)}</strong><div class='muted'>${escapeHtml(p.category || "other")} · ${escapeHtml(p.strategy_version || "legacy")} · Abierta ${dt(p.opened_at)}</div></td><td><span class='badge'>${escapeHtml(p.side)}</span></td><td>${Number(p.entry_price).toFixed(4)}</td><td>${mark.toFixed(4)}</td><td>${money(p.stake_usdc)}</td><td class='${pnlClass}'>${money(pnl)}</td><td>${pct(p.mfe_pct)}</td><td>${pct(p.mae_pct)}</td><td>${p.edge_gone_count || 0}/${settings.exitConfirmationCycles}</td></tr>`;
    })
    .join("");

  const closedRows = closedPositions
    .map(
      (p) =>
        `<tr><td>${escapeHtml(p.question)}<div class='muted'>${escapeHtml(p.strategy_version || "legacy")}</div></td><td>${escapeHtml(p.side)}</td><td>${Number(p.entry_price).toFixed(4)}</td><td>${Number(p.exit_price ?? 0).toFixed(4)}</td><td>${money(p.pnl_usdc)}</td><td>${escapeHtml(p.resolution || "-")}</td><td>${pct(p.mfe_pct)}</td><td>${pct(p.mae_pct)}</td><td>${dt(p.closed_at)}</td></tr>`,
    )
    .join("");

  const cycleRows = recentCycles
    .map(
      (c) =>
        `<tr><td>${c.id}</td><td>${dt(c.started_at)}</td><td>${c.markets_seen ?? 0}</td><td>${c.eligible ?? 0}</td><td>${c.analysed ?? 0}</td><td>${c.opened ?? 0}</td><td class='${c.error ? "negative" : "positive"}'>${c.error ? "ERROR" : "OK"}</td></tr>`,
    )
    .join("");

  const exposureTableRows = exposureRows
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.category)}</td><td>${row.positions}</td><td>${money(row.stake)}</td><td>${pct(Number(row.stake) / settings.bankrollUsdc)}</td></tr>`,
    )
    .join("");

  const rejectedRows = rejected
    .map(
      (row) =>
        `<tr><td>${dt(row.created_at)}</td><td>${escapeHtml(row.market_id || "-")}</td><td>${escapeHtml(row.reason || "-")}</td><td>${escapeHtml(row.strategy_version || "-")}</td></tr>`,
    )
    .join("");
  const decisionRows = decisions
    .map(
      (row) =>
        `<tr><td>${dt(row.created_at)}</td><td>${escapeHtml(row.action)}</td><td>${escapeHtml(row.reason || "-")}</td><td>${escapeHtml(row.market_id || "-")}</td></tr>`,
    )
    .join("");
  const confirmationRows = confirmations
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.market_id)}</td><td>${escapeHtml(row.side)}</td><td>${row.confirmations}/${settings.entryConfirmationCycles}</td><td>${pct(row.last_edge)}</td><td>${pct(row.last_confidence)}</td><td>${dt(row.last_seen_at)}</td></tr>`,
    )
    .join("");
  const healthRows = health
    .map(
      (row) =>
        `<tr><td>${escapeHtml(row.component)}</td><td>${row.consecutive_failures}</td><td>${dt(row.last_success_at)}</td><td>${escapeHtml(row.last_error || "-")}</td><td>${dt(row.paused_until)}</td></tr>`,
    )
    .join("");

  let peak: number | null = null;
  const drawdowns: number[] = [];
  for (const row of equityHistory) {
    const value = Number(row.equity);
    peak = peak === null ? value : Math.max(peak, value);
    drawdowns.push(peak ? (peak - value) / peak : 0);
  }

  const advancedMetrics = {
    ...summary,
    maxDrawdownPct: drawdowns.length ? Math.max(...drawdowns) : 0,
    currentDrawdownPct: drawdowns.length ? drawdowns[drawdowns.length - 1] : 0,
  };

  return page(
    "EL ROJILLA BOT",
    `<div class='topbar'><div><h1>EL ROJILLA BOT</h1><div class='muted'>Paper trading · Cloudflare Workers + D1 · Estrategia ${escapeHtml(settings.strategyVersion)} · Campaña ${escapeHtml(settings.campaignId)} · Refresco cada ${settings.dashboardRefreshSeconds}s</div></div><div class='status'><strong class='${stateClass}'>${state}</strong><div class='muted'>${escapeHtml(detail)}</div></div></div>
<div class='toolbar'><a class='button' href='/export/positions.csv'>Exportar posiciones</a><a class='button' href='/export/decision_ledger.csv'>Exportar decisiones</a><a class='button' href='/export/equity_history.csv'>Exportar equity</a></div>
<section class='cards'><div class='card'><div class='label'>Equity</div><div class='value'>${money(summary.equity)}</div></div><div class='card'><div class='label'>Rentabilidad</div><div class='value'>${pct(summary.returnPct)}</div></div><div class='card'><div class='label'>Drawdown actual</div><div class='value'>${pct(advancedMetrics.currentDrawdownPct)}</div></div><div class='card'><div class='label'>Drawdown máximo</div><div class='value'>${pct(advancedMetrics.maxDrawdownPct)}</div></div><div class='card'><div class='label'>Exposición</div><div class='value'>${money(summary.openStake)}</div><div class='muted'>${pct(summary.exposurePct)}</div></div><div class='card'><div class='label'>Win rate</div><div class='value'>${pct(summary.winRate)}</div></div><div class='card'><div class='label'>Profit factor</div><div class='value'>${summary.profitFactor === null ? "-" : summary.profitFactor.toFixed(2)}</div></div></section>
<div class='grid2'><div><h2>Curva de equity</h2>${svgLine(equityHistory.map((r) => Number(r.equity)), 1000, 220, true)}</div><div><h2>Drawdown</h2>${svgLine(drawdowns)}</div></div>
<div class='grid2'><div><h2>Exposición por categoría</h2>${exposureTableRows ? `<div class='table-wrap'><table><tr><th>Categoría</th><th>Posiciones</th><th>Stake</th><th>Bankroll</th></tr>${exposureTableRows}</table></div>` : "<div class='empty'>Sin exposición.</div>"}</div><div class='panel'><h2>Controles activos</h2><div class='muted'>Entrada ${settings.entryConfirmationCycles} ciclos · Reentrada ${settings.reopenCooldownDays} días · Máximo diario ${settings.maxNewPositionsPerDay} · Pausa drawdown ${pct(settings.pauseDrawdownPct)} · Pérdida diaria ${pct(settings.dailyLossLimitPct)} · TP ${pct(settings.takeProfitPct)} · SL ${pct(settings.stopLossPct)} · Trailing ${pct(settings.trailingStopPct)} tras ${pct(settings.trailingActivationPct)} · Edge-exit ${settings.edgeExitEnabled ? "ON" : "OFF"}</div></div></div>
<h2>Posiciones abiertas</h2>${openRows ? `<div class='table-wrap'><table><tr><th>Mercado</th><th>Lado</th><th>Entrada</th><th>Marca</th><th>Stake</th><th>uPnL</th><th>MFE</th><th>MAE</th><th>Conf. salida</th></tr>${openRows}</table></div>` : "<div class='empty'>No hay posiciones abiertas.</div>"}
<h2>Confirmaciones de entrada pendientes</h2>${confirmationRows ? `<div class='table-wrap'><table><tr><th>Mercado</th><th>Lado</th><th>Confirmaciones</th><th>Edge</th><th>Confianza</th><th>Última señal</th></tr>${confirmationRows}</table></div>` : "<div class='empty'>No hay entradas pendientes.</div>"}
<h2>Cerradas recientemente</h2>${closedRows ? `<div class='table-wrap'><table><tr><th>Mercado</th><th>Lado</th><th>Entrada</th><th>Salida</th><th>PnL</th><th>Motivo</th><th>MFE</th><th>MAE</th><th>Cierre</th></tr>${closedRows}</table></div>` : "<div class='empty'>No hay posiciones cerradas.</div>"}
<div class='grid2'><div><h2>Mercados rechazados</h2>${rejectedRows ? `<div class='table-wrap'><table><tr><th>Fecha</th><th>Mercado</th><th>Motivo</th><th>Versión</th></tr>${rejectedRows}</table></div>` : "<div class='empty'>No hay rechazos registrados.</div>"}</div><div><h2>Últimas decisiones</h2>${decisionRows ? `<div class='table-wrap'><table><tr><th>Fecha</th><th>Acción</th><th>Motivo</th><th>Mercado</th></tr>${decisionRows}</table></div>` : "<div class='empty'>No hay decisiones registradas.</div>"}</div></div>
<h2>Salud de componentes</h2>${healthRows ? `<div class='table-wrap'><table><tr><th>Componente</th><th>Fallos consecutivos</th><th>Último éxito</th><th>Último error</th><th>Pausa hasta</th></tr>${healthRows}</table></div>` : "<div class='empty'>Sin datos de salud.</div>"}
<h2>Ciclos recientes</h2><div class='table-wrap'><table><tr><th>ID</th><th>Inicio</th><th>Vistos</th><th>Elegibles</th><th>Analizados</th><th>Abiertos</th><th>Resultado</th></tr>${cycleRows}</table></div>`,
    true,
    settings.dashboardRefreshSeconds,
  );
}

export async function exportCsv(env: Env, table: string): Promise<Response> {
  const allowed = new Set(["positions", "analyses", "cycles", "equity_history", "decision_ledger"]);
  if (!allowed.has(table)) return new Response("Not found", { status: 404 });
  const { results } = await env.DB.prepare(`SELECT * FROM ${table}`).all();
  const rows = results as Record<string, unknown>[];
  if (rows.length === 0) return new Response("", { headers: { "Content-Type": "text/csv" } });
  const headers = Object.keys(rows[0]);
  const csvEscape = (value: unknown) => {
    const s = String(value ?? "");
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [headers.join(","), ...rows.map((row) => headers.map((h) => csvEscape(row[h])).join(","))];
  return new Response(lines.join("\n"), {
    headers: {
      "Content-Type": "text/csv",
      "Content-Disposition": `attachment; filename=${table}.csv`,
    },
  });
}
