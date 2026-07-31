import logging

from .polymarket import PolymarketClient
from .strategy import eligible, rank_market, build_opportunity
from .research import research_market
from .alerts import notify
from . import analytics, db, ops
from .config import settings

log = logging.getLogger(__name__)


def _select_markets_for_analysis(ranked, limit):
    open_ids = db.open_market_ids()
    recent_ids = db.recently_analyzed_market_ids(settings.analysis_cooldown_minutes)
    selected = []
    selected_ids = set()
    for market in ranked:
        if market.id in open_ids and market.id not in selected_ids:
            selected.append(market)
            selected_ids.add(market.id)
            if len(selected) >= limit:
                return selected
    for market in ranked:
        if market.id in selected_ids or market.id in recent_ids:
            continue
        selected.append(market)
        selected_ids.add(market.id)
        if len(selected) >= limit:
            break
    return selected


def run_cycle(scan_only=False):
    db.init_db()
    analytics.init_analytics()
    ops.prepare()
    cid = db.start_cycle()
    client = PolymarketClient()
    seen = analysed = opened = 0
    closed = []
    opened_details = []
    rejected_details = []
    degraded = False

    try:
        try:
            markets = client.list_active_markets()
            ops.component_success('polymarket')
        except Exception as exc:
            ops.component_failure('polymarket', exc)
            raise

        seen = len(markets)
        candidates = [m for m in markets if m.liquidity >= settings.min_liquidity and m.volume >= settings.min_volume]
        client.enrich_books(candidates)
        for market in markets:
            rank_market(market)
            db.save_snapshot(market)

        db.mark_positions(markets)
        ops.update_excursions()
        ranked = sorted((m for m in markets if eligible(m)), key=lambda m: m.rank_score, reverse=True)
        opportunities = []

        ai_available = settings.ai_enabled and ops.component_available('ai')
        if not scan_only and ai_available:
            market_limit = min(settings.analysis_top_n, max(1, settings.max_ai_calls_per_cycle // 2))
            selected = _select_markets_for_analysis(ranked, market_limit)
            ai_failures = 0
            for market in selected:
                try:
                    probability, critic = research_market(market)
                    opportunity = build_opportunity(market, probability, critic, db.exposure())
                    db.save_analysis(opportunity)
                    opportunities.append(opportunity)
                    analysed += 1
                    ops.ledger(
                        'ANALYSE', opportunity.decision, cycle_id=cid, market_id=str(market.id),
                        payload={'side': opportunity.side, 'edge': opportunity.net_edge,
                                 'confidence': opportunity.confidence, 'risk': opportunity.critic_risk,
                                 'stake': opportunity.stake_usdc},
                    )
                except Exception as exc:
                    ai_failures += 1
                    log.exception('analysis failed for %s', market.id)
                    ops.ledger('ANALYSIS_ERROR', str(exc), cycle_id=cid, market_id=str(market.id))
            if ai_failures:
                ops.component_failure('ai', f'{ai_failures} analysis failures in cycle {cid}')
                degraded = analysed == 0
            else:
                ops.component_success('ai')
        elif not scan_only:
            degraded = True
            ops.ledger('DEGRADED_MODE', 'AI unavailable; prices and exits only', cycle_id=cid)

        # Price-based exits continue in degraded mode. Edge exits only apply when a fresh opportunity exists.
        if not scan_only:
            closed = db.manage_exits(markets, opportunities)
            for item in closed:
                ops.ledger('CLOSE', item['reason'], cycle_id=cid, position_id=item['id'],
                           payload=item)
                notify(f"EL ROJILLA BOT closed #{item['id']}\n{item['reason']}\nPnL: ${item['pnl_usdc']:.2f}\n{item['question']}")

            open_ids = db.open_market_ids()
            for opportunity in opportunities:
                market_id = str(opportunity.market.id)
                if market_id in open_ids:
                    ops.ledger('HOLD', 'Existing open position', cycle_id=cid, market_id=market_id,
                               payload={'edge': opportunity.net_edge, 'decision': opportunity.decision})
                    continue

                allowed, reason, confirmation_count = ops.can_open(opportunity)
                if not allowed:
                    rejected = {'market_id': market_id, 'question': opportunity.market.question,
                                'reason': reason, 'confirmations': confirmation_count,
                                'decision': opportunity.decision, 'edge': opportunity.net_edge}
                    rejected_details.append(rejected)
                    ops.ledger('REJECT', reason, cycle_id=cid, market_id=market_id, payload=rejected)
                    continue

                if db.open_position(opportunity):
                    opened += 1
                    position_id = ops.tag_open_position(market_id, reason)
                    ops.clear_entry_confirmation(market_id)
                    detail = {'position_id': position_id, 'market_id': market_id,
                              'question': opportunity.market.question, 'side': opportunity.side,
                              'stake': opportunity.stake_usdc, 'strategy_version': settings.strategy_version,
                              'campaign_id': settings.campaign_id}
                    opened_details.append(detail)
                    ops.ledger('OPEN', reason, cycle_id=cid, market_id=market_id,
                               position_id=position_id, payload=detail)
                    notify(f"EL ROJILLA BOT opened {opportunity.side}\nStake: ${opportunity.stake_usdc:.2f}\nEdge: {opportunity.net_edge:.1%}\n{opportunity.market.question}")
                else:
                    ops.ledger('REJECT', 'DATABASE_OR_PORTFOLIO_LIMIT', cycle_id=cid,
                               market_id=market_id)

        db.finish_cycle(cid, seen, len(ranked), analysed, opened)
        metrics = analytics.record_equity()
        maintenance = ops.daily_maintenance()
        return {
            'seen': seen, 'eligible': len(ranked), 'analysed': analysed,
            'opened': opened, 'opened_details': opened_details,
            'rejected': len(rejected_details), 'rejected_details': rejected_details,
            'closed': len(closed), 'closed_details': closed,
            'degraded': degraded, 'maintenance': maintenance,
            'equity': metrics['equity'], 'total_pnl': metrics['total_pnl'],
            'top': ranked[:20], 'opportunities': opportunities,
        }
    except Exception as exc:
        db.finish_cycle(cid, seen, 0, analysed, opened, str(exc))
        ops.ledger('CYCLE_ERROR', str(exc), cycle_id=cid)
        try:
            analytics.record_equity()
        except Exception:
            log.exception('failed to record equity after cycle error')
        notify(f"EL ROJILLA BOT cycle error\n{type(exc).__name__}: {exc}")
        raise
    finally:
        client.close()
