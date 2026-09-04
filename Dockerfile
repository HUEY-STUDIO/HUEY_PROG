# 배포용 이미지. VPS 등 실제 서버에서:
#   docker build -t huey-prog .
#   docker run -d --name huey-prog -p 8000:8000 --env-file .env --restart unless-stopped huey-prog
# 자세한 순서는 docs/DEPLOY.md 참고.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# 인증키가 든 .env 는 이미지에 절대 넣지 않는다 — 실행 시 --env-file 로 주입한다
# (.dockerignore 가 빌드 컨텍스트에서부터 제외한다).
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request as u,sys; sys.exit(0 if u.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
