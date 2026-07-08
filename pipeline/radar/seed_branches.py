from datetime import datetime
from radar.db import get_engine, init_db
from sqlalchemy import text

branches = [
    "永豐金-匯立", "凱基-松山", "兆豐-復興", "富邦-南京", "元大-南京",
    "永豐金-南京", "統一-南京", "凱基-三多", "元大-南屯", "元大-信義",
    "康和-永和", "元大-館前", "港商麥格理", "元大-大天母", "凱基-信義",
    "592E", "法銀巴黎", "永豐金-板新", "永豐金-內湖", "兆豐-新竹", 
    "兆豐-中壢", "富邦-南港", "富邦-新竹", "富邦-新店",
    "富邦-嘉義", "元大-土城永寧", "統一-城中", "富邦-建國", "凱基-市政", "群益金鼎-大安"
]

def run():
    init_db()
    engine = get_engine()
    now = datetime.now().isoformat()
    with engine.begin() as conn:
        for b in branches:
            conn.execute(
                text("INSERT OR IGNORE INTO tracked_branches (branch_name, source, note, added_at) VALUES (:name, 'manual', '使用者指定種子分點', :now)"),
                {"name": b, "now": now}
            )
    print(f"Seeded {len(branches)} branches.")

if __name__ == "__main__":
    run()
