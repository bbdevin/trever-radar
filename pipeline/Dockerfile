# 管線映像(docs/31 §2):依賴烤進映像,程式碼與資料照既有慣例用 -v 掛載:
#   docker build -t radar-pipeline pipeline
#   docker run --rm -v $(pwd)/pipeline:/app/pipeline -v $(pwd)/data:/app/data \
#     radar-pipeline python -m radar <指令>
# requirements.txt 變更時需 rebuild(vps cron script 的 git pull 之後檢查)。
FROM python:3.11
ENV TZ=Asia/Taipei \
    PYTHONUNBUFFERED=1
WORKDIR /app/pipeline
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
CMD ["python", "-m", "radar", "--help"]
