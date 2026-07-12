# 盤中 worker 專用映像——build 一次,cron 每日 docker run --rm
# 設計要點:
# 1. 依賴預先裝進映像:08:50 啟動不依賴 PyPI 網路(開盤前 PyPI 慢/掛不會害 worker 缺席)
# 2. TZ 必須台北:worker.py 以 datetime.now()(本機時間)判斷 13:35 收工,
#    容器預設 UTC 會多跑 8 小時
# 3. 金鑰不進映像:一律由 docker run --env-file 傳入
FROM python:3.11-slim
ENV TZ=Asia/Taipei
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir \
    "fugle-marketdata>=2.4.1" "supabase>=2.31.0" "python-dotenv>=1.2.2" "requests>=2.31"
WORKDIR /app
COPY worker.py .
CMD ["python", "worker.py"]
