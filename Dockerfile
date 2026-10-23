FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OFFEROS_DATA_DIR=/var/lib/offeros \
    ENVIRONMENT=production \
    DISABLE_DOCS=true

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 offeros \
    && useradd --uid 10001 --gid offeros --no-create-home offeros \
    && mkdir -p /var/lib/offeros \
    && chown offeros:offeros /var/lib/offeros
COPY server ./server
COPY static ./static

USER offeros
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/healthz', timeout=3).close()"

# One process owns the in-process search/report workers and restart recovery.
CMD ["python", "-m", "server.start"]
