from concurrent.futures import ThreadPoolExecutor, as_completed
from .config import settings
from .db import init_db, save_snapshot, save_analysis, open_position
from .polymarket import PolymarketClient
from .research import research_market
from .strategy import evaluate


def scan(limit: int = 250, analyze: int = 10, execute: bool = False):
    init_db()
    markets = PolymarketClient().fetch_markets(limit)
    eligible = []
    for m in markets:
        save_snapshot(m)
        if (m.liquidity >= settings.min_liquidity_usdc and
            m.volume >= settings.min_volume_usdc and
            m.spread <= settings.max_spread and
            0.04 <= m.yes_price <= 0.96):
            eligible.append(m)
    # Prioritize liquidity and uncertainty; extreme prices are often poor LLM tasks.
    eligible.sort(key=lambda m: (m.liquidity * m.volume) ** 0.5 * (1 - abs(m.yes_price - .5)), reverse=True)
    targets = eligible[:analyze]
    opportunities = []
    with ThreadPoolExecutor(max_workers=min(4, max(1, len(targets)))) as pool:
        jobs = {pool.submit(research_market, m): m for m in targets}
        for job in as_completed(jobs):
            m = jobs[job]
            try:
                o = evaluate(m, job.result())
                save_analysis(o)
                if execute and o.decision == "PAPER_BUY":
                    open_position(o)
                opportunities.append(o)
            except Exception as exc:
                print(f"AVISO análisis fallido para {m.question[:60]}: {exc}")
    return sorted(opportunities, key=lambda o: o.score, reverse=True)
