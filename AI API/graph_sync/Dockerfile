FROM python:3.11-slim

# Install system dependencies (if any)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install
COPY ["AI API/requirements.txt", "requirements.txt"]
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker code only
COPY ["AI API/graph_sync/", "graph_sync/"]

# Default command (honours Cloud Run PORT semantics but not needed for worker)
EXPOSE 8080

CMD ["uvicorn", "graph_sync.main:app", "--host", "0.0.0.0", "--port", "8080"] 