"""Database pruning utilities."""
from sqlalchemy import text
from .db import get_engine, init_db

def prune_db(indicators_days: int = 400, warrants_days: int = 150, logs_days: int = 180, vacuum: bool = False) -> dict:
    init_db()
    engine = get_engine()
    
    with engine.connect() as conn:
        # Get cutoff date for indicators
        ind_cutoff = conn.execute(text(
            "SELECT date FROM (SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 1 OFFSET :n)"
        ), {"n": indicators_days}).scalar()
        
        # Get cutoff date for warrants
        war_cutoff = conn.execute(text(
            "SELECT date FROM (SELECT DISTINCT date FROM daily_prices ORDER BY date DESC LIMIT 1 OFFSET :n)"
        ), {"n": warrants_days}).scalar()

    with engine.begin() as conn:
        ind_deleted = 0
        if ind_cutoff:
            ind_deleted = conn.execute(text("DELETE FROM indicators_daily WHERE date < :d"), {"d": ind_cutoff}).rowcount
            
        war_deleted = 0
        if war_cutoff:
            war_deleted = conn.execute(text("DELETE FROM warrant_daily WHERE date < :d"), {"d": war_cutoff}).rowcount
            
        logs_deleted = conn.execute(text(
            "DELETE FROM import_logs WHERE date < date('now', :modifier)"
        ), {"modifier": f"-{logs_days} days"}).rowcount

    if vacuum:
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(text("VACUUM"))
            
    return {
        "indicators": ind_deleted,
        "warrants": war_deleted,
        "logs": logs_deleted,
        "vacuum": vacuum
    }
