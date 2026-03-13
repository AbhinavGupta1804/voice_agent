FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
  && rm -rf /var/lib/apt/lists/*

# Install backend dependencies
COPY agency_backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy only the backend code into the image
COPY agency_backend ./agency_backend

EXPOSE 8080

ENV PYTHONUNBUFFERED=1

# Use PORT from environment (Cloud Run sets this)
CMD ["sh", "-c", "uvicorn agency_backend.app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]