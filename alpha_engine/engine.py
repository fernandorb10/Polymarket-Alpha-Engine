import logging
from .polymarket import PolymarketClient
from .strategy import eligible, rank_market, build_opportunity
from .research import research_market
from .alerts import notify
from . import analytics, db
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
    cid = db.start_cycle()
    client = PolymarketClient()
    seen = analysed = opened = 0
    closed = []
    opened_details = []

    try:
        markets = client.list_active_markets()
        seen = len(markets)
        candidates = [m for m in markets if m.liquidity >= settings.min_liquidity and m.volume >= settings.min_volume]
        client.enrich_books(candidates)
        for market in markets:
            rank_market(market)
            db.save_snapshot(market)

        db.mark_positions(markets)
        ranked = sorted((m for m in markets if eligible(m)), key=lambda m: m.rank_score, reverse=True)
        opportunities = []

        if not scan_only:
            market_limit = min(settings.analysis_top_n, max(1, settings.max_ai_calls_per_cycle // 2))
            for market in _select_markets_for_analysis(ranked, market_limit):
                try:
                    probability, critic = research_market(market)
                    opportunity = build_opportunity(market, probability, critic, db.exposure())
                    db.save_analysis(opportunity)
                    opportunities.append(opportunity)
                    analysed += 1
                except Exception:
                    log.exception('analysis failed for %s', market.id)

            closed = db.manage_exits(markets, opportunities)
            for item in closed:
                notify(f"EL ROJILLA BOT closed #{item['id']}\n{item['reason']}\nPnL: ${item['pnl_usdc']:.2f}\n{item['question']}")

            for opportunity in opportunities:
                if db.open_position(opportunity):
                    opened += 1
                    opened_details.append({'market_id': opportunity.market.id, 'question': opportunity.market.question, 'side': opportunity.side, 'stake': opportunity.stake_usdc})
                    notify(f"EL ROJILLA BOT opened {opportunity.side}\nStake: ${opportunity.stake_usdc:.2f}\nEdge: {opportunity.net_edge:.1%}\n{opportunity.market.question}")

        db.finish_cycle(cid, seen, len(ranked), analysed, opened)
        metrics = analytics.record_equity()
        return {'seen': seen, 'eligible': len(ranked), 'analysed': analysed, 'opened': opened,
                'opened_details': opened_details, 'closed': len(closed), 'closed_details': closed,
                'equity': metrics['equity'], 'total_pnl': metrics['total_pnl'],
                'top': ranked[:20], 'opportunities': opportunities}
    except Exception as exc:
        db.finish_cycle(cid, seen, 0, analysed, opened, str(exc))
        try:
            analytics.record_equity()
        except Exception:
            log.exception('failed to record equity after cycle error')
        notify(f"EL ROJILLA BOT cycle error\n{type(exc).__name__}: {exc}")
        raise
    finally:
        client.close()
