# IgniteQuant always-on cloud cockpit (read-only viewer)
# Build: docker build -t ignitequant-cockpit .
# Run:   docker run --rm -p 8787:8787 -e DATABASE_URL=... -e SIM_DATA_SOURCE=cloud ignitequant-cockpit

FROM node:22-bookworm AS web-build
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app:/app/src \
    SIM_DATA_SOURCE=cloud \
    PORT=8787

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard ./dashboard
COPY src ./src
COPY strategies ./strategies
COPY configs ./configs
COPY --from=web-build /app/web/dist ./web/dist

EXPOSE 8787
CMD ["uvicorn", "dashboard.api:app", "--host", "0.0.0.0", "--port", "8787"]
