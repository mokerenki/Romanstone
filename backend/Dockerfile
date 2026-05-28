# Aether Backend — Production Dockerfile
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends     gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install chromium && playwright install-deps chromium

COPY . .
RUN mkdir -p /tmp/aether/sandbox
RUN useradd -m -u 1000 aether && chown -R aether:aether /app /tmp/aether
USER aether

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3     CMD curl -f http://localhost:8000/api/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
