FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Run DB migrations, then start. $PORT injected by host; 8000 locally.
# Migrations must not block startup if the DB is briefly unreachable.
CMD ["sh", "-c", "alembic upgrade head || echo 'WARN: migrations failed, starting anyway'; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
