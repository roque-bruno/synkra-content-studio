FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

# Install system dependencies (ffmpeg for video assembler, curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy backend
COPY packages/content-pipeline/pyproject.toml ./
RUN touch README.md
COPY packages/content-pipeline/src/ ./src/

# Install dependencies
RUN pip install --no-cache-dir -e .

# Copy frontend for same-origin serving
COPY packages/content-studio-frontend/ ./frontend/

# Create output directories with correct permissions
RUN mkdir -p /app/output/studio /app/output/video /app/output/logs && \
    chown -R appuser:appuser /app/output /app/frontend

# Switch to non-root user
USER appuser

EXPOSE 10000

CMD ["sh", "-c", "uvicorn content_pipeline.web.app:app --host 0.0.0.0 --port ${PORT:-10000}"]
