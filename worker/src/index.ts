import { loadSettings } from "./config";
import * as dashboard from "./dashboard";
import * as db from "./db";
import { runCycle } from "./engine";
import type { Env } from "./types";

const SELF_URL = "https://el-rojilla-bot.frodriguezbraojos.workers.dev";

export default {
  // Cron-triggered `scheduled()` invocations on this plan get killed before
  // ctx.waitUntil(runCycle(...)) finishes - every cycle since deploy stayed
  // stuck at started_at with no finished_at or error, while the exact same
  // runCycle() reliably completes in 1-8s when invoked through fetch() (e.g.
  // manual /run calls all finished fine). So scheduled() no longer runs the
  // cycle itself - it just fires a self-request at /run, which executes in a
  // normal fetch-triggered context that has proven to complete reliably.
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const settings = loadSettings(env);
    const headers: Record<string, string> = {};
    if (settings.dashboardUsername && settings.dashboardPassword) {
      headers.Authorization = `Basic ${btoa(`${settings.dashboardUsername}:${settings.dashboardPassword}`)}`;
    }
    ctx.waitUntil(
      fetch(`${SELF_URL}/run`, { method: "POST", headers }).catch((err) => {
        console.error("failed to trigger cycle via self-fetch", err);
      }),
    );
  },

  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const settings = loadSettings(env);
    const url = new URL(request.url);

    const authFailure = dashboard.requireAuth(request, settings);
    if (authFailure) return authFailure;

    if (url.pathname === "/health") {
      const latest = await db.latestCycle(env);
      return Response.json({ latest_cycle: latest });
    }

    if (url.pathname === "/api/status") {
      const summary = await db.summary(env, settings);
      return Response.json(summary);
    }

    if (url.pathname === "/api/positions") {
      return Response.json(await db.listPositions(env));
    }

    if (url.pathname === "/api/cycles") {
      return Response.json(await db.recentCycles(env, 50));
    }

    if (url.pathname.startsWith("/export/") && url.pathname.endsWith(".csv")) {
      const table = url.pathname.slice("/export/".length, -".csv".length);
      return dashboard.exportCsv(env, table);
    }

    if (url.pathname === "/run" && request.method === "POST") {
      // Manual trigger for testing; same auth gate as the dashboard.
      ctx.waitUntil(runCycle(env, settings).catch((err) => console.error("manual run_cycle failed", err)));
      return new Response("Cycle started", { status: 202 });
    }

    if (url.pathname === "/" || url.pathname === "") {
      const html = await dashboard.renderHome(env, settings);
      return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    return new Response("Not found", { status: 404 });
  },
};
