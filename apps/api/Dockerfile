FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY apps/api apps/api
COPY services/workflow-worker services/workflow-worker
RUN pip install --no-cache-dir .
COPY data data
ENV OPERATOR_DATA_DIR=/app/data/demo
COPY scripts scripts
COPY infra/migrations infra/migrations
CMD ["sh", "-c", "python scripts/migrate.py && uvicorn operator_api.main:app --host 0.0.0.0 --port 8000"]
