import logging
from .polymarket import PolymarketClient
from .strategy import eligible, rank_market, build_opportunity
from .research import research_market
from . import db
from .config import settings
log=logging.getLogger(__name__)

def run_cycle(scan_only=False):
    db.init_db(); cid=db.start_cycle(); client=PolymarketClient(); seen=analysed=opened=0
    try:
      markets=client.list_active_markets(); seen=len(markets)
      candidates=[m for m in markets if m.liquidity>=settings.min_liquidity and m.volume>=settings.min_volume]
      client.enrich_books(candidates)
      for m in markets: rank_market(m); db.save_snapshot(m)
      db.mark_positions(markets)
      ranked=sorted((m for m in markets if eligible(m)),key=lambda m:m.rank_score,reverse=True)
      opportunities=[]
      if not scan_only:
        for m in ranked[:min(settings.analysis_top_n,settings.max_ai_calls_per_cycle)]:
          try:
            p,c=research_market(m); o=build_opportunity(m,p,c,db.exposure()); db.save_analysis(o); analysed+=1
            if db.open_position(o): opened+=1
            opportunities.append(o)
          except Exception: log.exception('analysis failed for %s',m.id)
      db.finish_cycle(cid,seen,len(ranked),analysed,opened)
      return {'seen':seen,'eligible':len(ranked),'analysed':analysed,'opened':opened,'top':ranked[:20],'opportunities':opportunities}
    except Exception as e:
      db.finish_cycle(cid,seen,0,analysed,opened,str(e)); raise
    finally: client.close()
