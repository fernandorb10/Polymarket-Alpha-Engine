import { loadSettings } from "./config";
import * as dashboard from "./dashboard";
import * as db from "./db";
import { runCycle } from "./engine";
import type { Env } from "./types";

export default {
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    const settings = loadSettings(env);
    ctx.waitUntil(
      runCycle(env, settings).catch((err) => {
        console.error("run_cycle failed", err);
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
