import { notify } from "./alerts";
import type { Settings } from "./config";
import * as db from "./db";
import { categoryCounts, marketCategory, selectBalanced } from "./marketSelection";
import * as ops from "./ops";
import { enrichBooks, listActiveMarkets } from "./polymarket";
import { researchMarket } from "./research";
import { buildOpportunity, eligible, rankMarket } from "./strategy";
import type { Env, Market, Opportunity } from "./types";

async function pendingConfirmationIds(env: Env, settings: Settings): Promise<Set<string>> {
  const cutoff = new Date(
    Date.now() - settings.entryConfirmationExpiryMinutes * 60000,
  ).toISOString();
  await env.DB.prepare("DELETE FROM entry_confirmations WHERE last_seen_at<?").bind(cutoff).run();
  const { results } = await env.DB.prepare(
    "SELECT market_id FROM entry_confirmations WHERE confirmations<? AND last_seen_at>=?",
  )
    .bind(settings.entryConfirmationCycles, cutoff)
    .all();
  return new Set(results.map((row) => String((row as Record<string, unknown>).market_id)));
}

async function selectMarketsForAnalysis(
  env: Env,
  settings: Settings,
  ranked: Market[],
  limit: number,
  pendingIds: Set<string>,
): Promise<Market[]> {
  const openIds = await db.openMarketIdsByOldestAnalysis(env);
  const recentIds = await db.recentlyAnalyzedMarketIds(env, settings.analysisCooldownMinutes);
  const diversityRecentIds = await db.recentlyAnalyzedMarketIds(
    env,
    settings.diversityCooldownMinutes,
  );
  return selectBalanced(settings, ranked, limit, openIds, recentIds, diversityRecentIds, pendingIds);
}

export interface CycleResult {
  seen: number;
  eligible: number;
  analysed: number;
  opened: number;
  rejected: number;
  closed: number;
  degraded: boolean;
  equity: number;
  totalPnl: number;
}

export async function runCycle(env: Env, settings: Settings, scanOnly = false): Promise<CycleResult> {
  await ops.ensureCampaign(env, settings);
  const cycleId = await db.startCycle(env);

  let seen = 0;
  let analysed = 0;
  let opened = 0;
  let closedCount = 0;
  let degraded = false;
  const rejectedDetails: Record<string, unknown>[] = [];

  try {
    let markets: Market[];
    try {
      markets = await listActiveMarkets(settings);
      await ops.componentSuccess(env, "polymarket");
    } catch (exc) {
      await ops.componentFailure(env, settings, "polymarket", exc);
      throw exc;
    }

    seen = markets.length;
    const seenByCategory = categoryCounts(markets);

    const candidates = markets.filter(
      (market) => market.liquidity >= settings.minLiquidity && market.volume >= settings.minVolume,
    );
    await enrichBooks(settings, candidates);

    for (const market of markets) rankMarket(market, settings);
    await db.saveSnapshots(env, markets);
    await db.markPositions(env, markets);
    await ops.updateExcursions(env);

    const ranked = markets
      .filter((market) => eligible(market, settings))
      .sort((a, b) => b.rankScore - a.rankScore);
    const eligibleByCategory = categoryCounts(ranked);
    const opportunities: Opportunity[] = [];
    const pendingIds = await pendingConfirmationIds(env, settings);

    const aiAvailable = settings.aiEnabled && (await ops.componentAvailable(env, "ai"));
    if (!scanOnly && aiAvailable) {
      const marketLimit = Math.min(
        settings.analysisTopN,
        Math.max(1, Math.floor(settings.maxAiCallsPerCycle / 2)),
      );
      const selected = await selectMarketsForAnalysis(env, settings, ranked, marketLimit, pendingIds);

      let aiFailures = 0;
      const analysedCategories: string[] = [];
      for (const market of selected) {
        try {
          const [probability, critic] = await researchMarket(settings, market);
          const opportunity = buildOpportunity(
            market,
            probability,
            critic,
            await db.exposure(env),
            settings,
          );
          await db.saveAnalysis(env, opportunity);
          opportunities.push(opportunity);
          analysed += 1;
          analysedCategories.push(marketCategory(market));
          await ops.ledger(env, settings, "ANALYSE", opportunity.decision, {
            cycleId,
            marketId: String(market.id),
            payload: {
              category: marketCategory(market),
              side: opportunity.side,
              edge: opportunity.netEdge,
              confidence: opportunity.confidence,
              risk: opportunity.criticRisk,
              stake: opportunity.stakeUsdc,
              evidence_count: opportunity.probabilityReport.source_urls.length,
            },
          });
        } catch (exc) {
          aiFailures += 1;
          await ops.ledger(env, settings, "ANALYSIS_ERROR", String(exc), {
            cycleId,
            marketId: String(market.id),
            payload: { category: marketCategory(market) },
          });
        }
      }

      if (aiFailures) {
        await ops.componentFailure(env, settings, "ai", `${aiFailures} analysis failures in cycle ${cycleId}`);
        degraded = analysed === 0;
      } else {
        await ops.componentSuccess(env, "ai");
      }
    } else if (!scanOnly) {
      degraded = true;
      await ops.ledger(env, settings, "DEGRADED_MODE", "AI unavailable; prices and exits only", { cycleId });
    }

    await ops.ledger(
      env,
      settings,
      "SCAN_STATS",
      `${seen} seen / ${ranked.length} eligible / ${analysed} analysed`,
      { cycleId, payload: { seenByCategory, eligibleByCategory } },
    );

    if (!scanOnly) {
      const closed = await db.manageExits(env, settings, markets, opportunities);
      closedCount = closed.length;
      for (const item of closed) {
        await ops.ledger(env, settings, "CLOSE", item.reason, {
          cycleId,
          positionId: item.id,
          payload: item,
        });
        await notify(
          settings,
          `EL ROJILLA BOT closed #${item.id}\n${item.reason}\nPnL: $${item.pnlUsdc.toFixed(2)}\n${item.question}`,
        );
      }

      const openIds = await db.openMarketIds(env);
      for (const opportunity of opportunities) {
        const marketId = String(opportunity.market.id);
        if (openIds.has(marketId)) {
          await ops.ledger(env, settings, "HOLD", "Existing open position", {
            cycleId,
            marketId,
            payload: {
              category: marketCategory(opportunity.market),
              edge: opportunity.netEdge,
              decision: opportunity.decision,
            },
          });
          continue;
        }

        if (opportunity.decision !== "OPEN") {
          await ops.clearEntryConfirmation(env, marketId);
        }

        const [allowed, reason, confirmationCount] = await ops.canOpen(env, settings, opportunity);
        if (!allowed) {
          const rejected = {
            market_id: marketId,
            question: opportunity.market.question,
            category: marketCategory(opportunity.market),
            reason,
            confirmations: confirmationCount,
            decision: opportunity.decision,
            edge: opportunity.netEdge,
          };
          rejectedDetails.push(rejected);
          await ops.ledger(env, settings, "REJECT", reason, { cycleId, marketId, payload: rejected });
          continue;
        }

        const [room, portfolioReason] = await db.maxAllowedStake(
          env,
          settings,
          opportunity.market.question,
          opportunity.market.category,
        );
        if (room < 1) {
          const rejected = {
            market_id: marketId,
            question: opportunity.market.question,
            category: marketCategory(opportunity.market),
            reason: portfolioReason || "PORTFOLIO_LIMIT",
            confirmations: confirmationCount,
            decision: opportunity.decision,
            edge: opportunity.netEdge,
          };
          rejectedDetails.push(rejected);
          await ops.ledger(env, settings, "REJECT", rejected.reason, { cycleId, marketId, payload: rejected });
          continue;
        }

        if (await db.openPosition(env, settings, opportunity)) {
          opened += 1;
          const positionId = await ops.tagOpenPosition(env, settings, marketId, reason);
          await ops.clearEntryConfirmation(env, marketId);
          const detail = {
            position_id: positionId,
            market_id: marketId,
            question: opportunity.market.question,
            category: marketCategory(opportunity.market),
            side: opportunity.side,
            stake: opportunity.stakeUsdc,
            strategy_version: settings.strategyVersion,
            campaign_id: settings.campaignId,
          };
          await ops.ledger(env, settings, "OPEN", reason, {
            cycleId,
            marketId,
            positionId: positionId ?? undefined,
            payload: detail,
          });
          await notify(
            settings,
            `EL ROJILLA BOT opened ${opportunity.side}\nStake: $${opportunity.stakeUsdc.toFixed(2)}\nEdge: ${(opportunity.netEdge * 100).toFixed(1)}%\n${opportunity.market.question}`,
          );
        } else {
          await ops.ledger(env, settings, "REJECT", "DATABASE_OR_PORTFOLIO_LIMIT", { cycleId, marketId });
        }
      }
    }

    await db.finishCycle(env, cycleId, seen, ranked.length, analysed, opened);
    const metrics = await ops.recordEquity(env, settings);
    await ops.dailyMaintenance(env, settings);

    return {
      seen,
      eligible: ranked.length,
      analysed,
      opened,
      rejected: rejectedDetails.length,
      closed: closedCount,
      degraded,
      equity: metrics.equity,
      totalPnl: metrics.totalPnl,
    };
  } catch (exc) {
    await db.finishCycle(env, cycleId, seen, 0, analysed, opened, String(exc));
    await ops.ledger(env, settings, "CYCLE_ERROR", String(exc), { cycleId });
    try {
      await ops.recordEquity(env, settings);
    } catch {
      // best effort
    }
    await notify(settings, `EL ROJILLA BOT cycle error\n${exc}`);
    throw exc;
  }
}
