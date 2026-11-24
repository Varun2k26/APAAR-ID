# Single image: build the React app, then serve it and the API from FastAPI on :8000.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy
RUN pip install --no-cache-dir uv==0.11.28
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/ ./
COPY tools/ /app/tools/
COPY --from=web /web/dist /app/frontend/dist
ENV APAAR_DATA_DIR=/app/data
EXPOSE 8000
CMD ["sh", "-c", "[ -f /app/data/apaar.db ] || uv run --no-dev python -m seed.generate; exec uv run --no-dev uvicorn app.main:app --host 0.0.0.0 --port 8000"]
