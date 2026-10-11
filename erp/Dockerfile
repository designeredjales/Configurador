FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    ERP_AMBIENTE=producao ERP_CRIAR_TABELAS=0

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY migrations ./migrations
COPY alembic.ini docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh && useradd --create-home --uid 10001 erp \
    && mkdir -p /app/arquivos && chown erp /app/arquivos
USER erp

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/saude', timeout=4)"
ENTRYPOINT ["./docker-entrypoint.sh"]
