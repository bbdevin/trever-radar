import pandas as pd
from datetime import datetime
from radar.db import get_engine

def compute_all():
    """Computes branch stock stats and branch rankings for tracked branches."""
    engine = get_engine()
    
    # 1. Get tracked branches
    tracked_df = pd.read_sql("SELECT branch_name FROM tracked_branches", engine)
    if tracked_df.empty:
        print("No tracked branches found.")
        return
    tracked_names = tuple(tracked_df['branch_name'].tolist())
    if len(tracked_names) == 1:
        tracked_names = f"('{tracked_names[0]}')"
    
    # 2. Get their trades
    trades_query = f"""
        SELECT date, stock_id, branch_name, buy_lots, sell_lots, net_lots, pct
        FROM branch_trades
        WHERE branch_name IN {tracked_names}
    """
    trades_df = pd.read_sql(trades_query, engine)
    if trades_df.empty:
        print("No trades found for tracked branches.")
        return
        
    # We only care about buy events for win rate
    buy_events = trades_df[trades_df['net_lots'] > 0].copy()
    
    # In a real scenario we'd join with daily_prices to get next day's open and day+5 close.
    # Since we lack data right now, we will put placeholders for win_rate and avg_ret5.
    
    # 3. Aggregate branch_stock_stats
    stats_df = buy_events.groupby(['branch_name', 'stock_id']).agg(
        events_count=('date', 'count'),
        last_active_date=('date', 'max')
    ).reset_index()
    stats_df['win_rate'] = None
    stats_df['avg_ret5'] = None
    stats_df['is_daytrade_suspect'] = False
    stats_df['updated_at'] = datetime.now().isoformat()
    
    # Upsert branch_stock_stats
    from radar.db import upsert
    from radar.schema import branch_stock_stats
    with engine.begin() as conn:
        conn.execute(branch_stock_stats.delete()) # Clear old
        upsert(conn, branch_stock_stats, stats_df.to_dict(orient='records'))
        
    # 4. Aggregate branch_rankings
    rank_df = stats_df.groupby('branch_name').agg(
        samples=('events_count', 'sum')
    ).reset_index()
    rank_df['as_of'] = datetime.now().strftime('%Y-%m-%d')
    rank_df['rank_score'] = 50.0  # Placeholder baseline
    rank_df['win_rate'] = None
    rank_df['avg_ret5'] = None
    rank_df['style'] = 'swing'
    rank_df['is_daytrade'] = False
    rank_df['source'] = 'manual'
    
    from radar.schema import branch_rankings
    with engine.begin() as conn:
        conn.execute(branch_rankings.delete())
        upsert(conn, branch_rankings, rank_df.to_dict(orient='records'))
        
    print(f"Computed stats for {len(rank_df)} branches.")

if __name__ == "__main__":
    compute_all()
