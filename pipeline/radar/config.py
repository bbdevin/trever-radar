import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root
DATA_DIR = Path(os.environ.get("RADAR_DATA_DIR", str(ROOT / "data")))
DB_URL = os.environ.get("RADAR_DB_URL", "sqlite:///" + (DATA_DIR / "radar.db").as_posix())

HTTP_TIMEOUT = 30
HTTP_RETRIES = 3
HTTP_BACKOFF = 5.0          # seconds, multiplied by attempt number
THROTTLE_SECONDS = 3.0      # min interval between requests (be polite to TWSE/TPEx)
USER_AGENT = "Mozilla/5.0 (TreverRadar; private research tool)"

TZ = "Asia/Taipei"
