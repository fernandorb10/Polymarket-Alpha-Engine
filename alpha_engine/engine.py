import logging
from collections import Counter
from datetime import timedelta

from . import analytics, db, ops
from .alerts import notify
from .config import settings
from .market_selection import category_counts, market_category, select_balanced
from .polymarket import PolymarketClient
from .research import research_market
from .strategy import build_opportunity, eligible, rank_market

log = logging.getLogger(__name__)


def _pending_confirmation_ids() -> set[str]:
    cutoff = (
        ops.utcnow()
        - timedelta(minutes=settings.entry_confirmation_expiry_minutes)
    ).isoformat()
    with ops.connect() as conn:
        conn.execute(
            "DELETE FROM entry_confirmations WHERE last_seen_at<?",
            (cutoff,),
        )
        rows = conn.execute(
            """
            SELECT market_id
            FROM entry_confirmations
            WHERE confirmations<? AND last_seen_at>=?
            """,
            (settings.entry_confirmation_cycles, cutoff),
        )
    return {str(row["market_id"]) for row in rows}


def _select_markets_for_analysis(ranked, limit: int, pending_ids: set[str]):
    return select_balanced(
        ranked,
        limit,
        db.open_market_ids_by_oldest_analysis(),
        db.recently_analyzed_market_ids(settings.analysis_cooldown_minutes),
        db.recently_analyzed_market_ids(settings.diversity_cooldown_minutes),
        pending_ids,
    )


def _analysis_payload(market, opportunity) -> dict:
    report = opportunity.probability_report
    return {
        "category": market_category(market),
        "side": opportunity.side,
        "edge": opportunity.net_edge,
        "confidence": opportunity.confidence,
        "risk": opportunity.critic_risk,
        "stake": opportunity.stake_usdc,
        "evidence_count": len(report.source_urls),
        "source_urls": report.source_urls,
        "evidence": report.evidence,
        "unknowns": report.unknowns,
    }


def run_cycle(scan_only: bool = False):
    db.init_db()
    analytics.init_analytics()
    ops.prepare()

    cycle_id = db.start_cycle()
    client = PolymarketClient()
    seen = 0
    analysed = 0
    opened = 0
    closed = []
    opened_details = []
    rejected_details = []
    degraded = False
    seen_by_category = {}
    eligible_by_category = {}
    analysed_by_category = {}
    selected_questions = []

    try:
        try:
            markets = client.list_active_markets()
            ops.component_success("polymarket")
        except Exception as exc:
            ops.component_failure("polymarket", exc)
            raise

        seen = len(markets)
        seen_by_category = category_counts(markets)
        candidates = [
            market
            for market in markets
            if market.liquidity >= settings.min_liquidity
            and market.volume >= settings.min_volume
        ]
        client.enrich_books(candidates)

        for market in markets:
            rank_market(market)
        db.save_snapshots(markets)
        db.mark_positions(markets)
        ops.update_excursions()

        ranked = sorted(
            (market for market in markets if eligible(market)),
            key=lambda market: market.rank_score,
            reverse=True,
        )
        eligible_by_category = category_counts(ranked)
        opportunities = []
        pending_ids = _pending_confirmation_ids()

        ai_available = settings.ai_enabled and ops.component_available("ai")
        if not scan_only and ai_available:
            market_limit = min(
                settings.analysis_top_n,
                max(1, settings.max_ai_calls_per_cycle // 2),
            )
            selected = _select_markets_for_analysis(
                ranked,
                market_limit,
                pending_ids,
            )
            selected_questions = [
                {
                    "market_id": str(market.id),
                    "category": market_category(market),
                    "score": market.rank_score,
                    "question": market.question,
                    "pending_confirmation": str(market.id) in pending_ids,
                }
                for market in selected
            ]

            ai_failures = 0
            analysed_categories = []
            for market in selected:
                try:
                    probability, critic = research_market(market)
                    opportunity = build_opportunity(
                        market,
                        probability,
                        critic,
                        db.exposure(),
                    )
                    db.save_analysis(opportunity)
                    opportunities.append(opportunity)
                    analysed += 1
                    analysed_categories.append(market_category(market))
                    ops.ledger(
                        "ANALYSE",
                        opportunity.decision,
                        cycle_id=cycle_id,
                        market_id=str(market.id),
                        payload=_analysis_payload(market, opportunity),
                    )
                except Exception as exc:
                    ai_failures += 1
                    log.exception("analysis failed for %s", market.id)
                    ops.ledger(
                        "ANALYSIS_ERROR",
                        str(exc),
                        cycle_id=cycle_id,
                        market_id=str(market.id),
                        payload={"category": market_category(market)},
                    )

            analysed_by_category = dict(
                sorted(Counter(analysed_categories).items())
            )
            if ai_failures:
                ops.component_failure(
                    "ai",
                    f"{ai_failures} analysis failures in cycle {cycle_id}",
                )
                degraded = analysed == 0
            else:
                ops.component_success("ai")
        elif not scan_only:
            degraded = True
            ops.ledger(
                "DEGRADED_MODE",
                "AI unavailable; prices and exits only",
                cycle_id=cycle_id,
            )

        ops.ledger(
            "SCAN_STATS",
            f"{seen} seen / {len(ranked)} eligible / {analysed} analysed",
            cycle_id=cycle_id,
            payload={
                "seen_by_category": seen_by_category,
                "eligible_by_category": eligible_by_category,
                "analysed_by_category": analysed_by_category,
                "selected": selected_questions,
            },
        )

        if not scan_only:
            closed = db.manage_exits(markets, opportunities)
            for item in closed:
                ops.ledger(
                    "CLOSE",
                    item["reason"],
                    cycle_id=cycle_id,
                    position_id=item["id"],
                    payload=item,
                )
                notify(
                    f"EL ROJILLA BOT closed #{item['id']}\n"
                    f"{item['reason']}\n"
                    f"PnL: ${item['pnl_usdc']:.2f}\n"
                    f"{item['question']}"
                )

            open_ids = db.open_market_ids()
            for opportunity in opportunities:
                market_id = str(opportunity.market.id)
                if market_id in open_ids:
                    ops.ledger(
                        "HOLD",
                        "Existing open position",
                        cycle_id=cycle_id,
                        market_id=market_id,
                        payload={
                            "category": market_category(opportunity.market),
                            "edge": opportunity.net_edge,
                            "decision": opportunity.decision,
                        },
                    )
                    continue

                if opportunity.decision != "OPEN":
                    ops.clear_entry_confirmation(market_id)

                allowed, reason, confirmation_count = ops.can_open(opportunity)
                if not allowed:
                    rejected = {
                        "market_id": market_id,
                        "question": opportunity.market.question,
                        "category": market_category(opportunity.market),
                        "reason": reason,
                        "confirmations": confirmation_count,
                        "decision": opportunity.decision,
                        "edge": opportunity.net_edge,
                    }
                    rejected_details.append(rejected)
                    ops.ledger(
                        "REJECT",
                        reason,
                        cycle_id=cycle_id,
                        market_id=market_id,
                        payload=rejected,
                    )
                    continue

                room, portfolio_reason = db.max_allowed_stake(
                    opportunity.market.question,
                    opportunity.market.category,
                )
                if room < 1:
                    rejected = {
                        "market_id": market_id,
                        "question": opportunity.market.question,
                        "category": market_category(opportunity.market),
                        "reason": portfolio_reason or "PORTFOLIO_LIMIT",
                        "confirmations": confirmation_count,
                        "decision": opportunity.decision,
                        "edge": opportunity.net_edge,
                    }
                    rejected_details.append(rejected)
                    ops.ledger(
                        "REJECT",
                        rejected["reason"],
                        cycle_id=cycle_id,
                        market_id=market_id,
                        payload=rejected,
                    )
                    continue

                if db.open_position(opportunity):
                    opened += 1
                    position_id = ops.tag_open_position(market_id, reason)
                    ops.clear_entry_confirmation(market_id)
                    detail = {
                        "position_id": position_id,
                        "market_id": market_id,
                        "question": opportunity.market.question,
                        "category": market_category(opportunity.market),
                        "side": opportunity.side,
                        "stake": opportunity.stake_usdc,
                        "strategy_version": settings.strategy_version,
                        "campaign_id": settings.campaign_id,
                    }
                    opened_details.append(detail)
                    ops.ledger(
                        "OPEN",
                        reason,
                        cycle_id=cycle_id,
                        market_id=market_id,
                        position_id=position_id,
                        payload=detail,
                    )
                    notify(
                        f"EL ROJILLA BOT opened {opportunity.side}\n"
                        f"Stake: ${opportunity.stake_usdc:.2f}\n"
                        f"Edge: {opportunity.net_edge:.1%}\n"
                        f"{opportunity.market.question}"
                    )
                else:
                    ops.ledger(
                        "REJECT",
                        "DATABASE_OR_PORTFOLIO_LIMIT",
                        cycle_id=cycle_id,
                        market_id=market_id,
                    )

        db.finish_cycle(
            cycle_id,
            seen,
            len(ranked),
            analysed,
            opened,
        )
        metrics = analytics.record_equity()
        maintenance = ops.daily_maintenance()
        return {
            "seen": seen,
            "seen_by_category": seen_by_category,
            "eligible": len(ranked),
            "eligible_by_category": eligible_by_category,
            "analysed": analysed,
            "analysed_by_category": analysed_by_category,
            "selected": selected_questions,
            "opened": opened,
            "opened_details": opened_details,
            "rejected": len(rejected_details),
            "rejected_details": rejected_details,
            "closed": len(closed),
            "closed_details": closed,
            "degraded": degraded,
            "maintenance": maintenance,
            "equity": metrics["equity"],
            "total_pnl": metrics["total_pnl"],
            "top": ranked[:20],
            "opportunities": opportunities,
        }
    except Exception as exc:
        db.finish_cycle(cycle_id, seen, 0, analysed, opened, str(exc))
        ops.ledger("CYCLE_ERROR", str(exc), cycle_id=cycle_id)
        try:
            analytics.record_equity()
        except Exception:
            log.exception("failed to record equity after cycle error")
        notify(
            f"EL ROJILLA BOT cycle error\n{type(exc).__name__}: {exc}"
        )
        raise
    finally:
        client.close()
