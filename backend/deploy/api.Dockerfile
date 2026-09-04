# Build context is the backend/ directory.
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/libs:/app

COPY pyproject.toml ./
COPY libs ./libs
RUN pip install --no-cache-dir -e ".[api,azure,data,telemetry,gemini]"

COPY apps ./apps
COPY evals ./evals
COPY corpus ./corpus

EXPOSE 8000
CMD ["uvicorn", "apps.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
