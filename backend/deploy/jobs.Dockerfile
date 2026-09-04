# Build context is the backend/ directory.
# Ingest job and evaluator share an image; the Container Apps Job command
# selects which entry point runs.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/libs:/app

COPY pyproject.toml ./
COPY libs ./libs
RUN pip install --no-cache-dir -e ".[azure,data,eval]"

COPY apps ./apps
COPY evals ./evals

CMD ["python", "-m", "apps.ingest.main", "--queue"]
