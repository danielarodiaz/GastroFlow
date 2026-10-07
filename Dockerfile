FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev curl unzip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN APP_SECRET_KEY=build-time-secret \
    DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/database \
    reflex compile --loglevel warning --no-rich

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://127.0.0.1:3000/ping || exit 1

CMD ["reflex", "run", "--env", "prod", "--single-port", "--frontend-port", "3000", "--backend-host", "0.0.0.0"]
