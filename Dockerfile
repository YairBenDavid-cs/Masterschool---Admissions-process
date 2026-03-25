# 1. Base Image — slim for a smaller, more secure footprint
FROM python:3.12-slim

# 2. Environment Variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# 3. Working directory
WORKDIR /app

# 4. System dependencies — curl is required for the HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# 5. Install Python dependencies first (leverages Docker layer cache on rebuilds)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 6. Copy application source
COPY . .

# 7. Non-root user for security — reduces blast radius if the container is compromised
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

# 8. Expose API port
EXPOSE 8000

# 9. Health check — polls the /health endpoint built into the app
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# 10. Start the FastAPI app via Uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
