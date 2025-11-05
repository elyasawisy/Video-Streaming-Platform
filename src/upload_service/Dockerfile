FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/upload_service/ ./src/upload_service/
COPY src/shared/ ./src/shared/

# Create upload directories
RUN mkdir -p /app/uploads/raw

# Expose port
EXPOSE 8001

# Use Hypercorn for HTTP/2 support
CMD ["hypercorn", "src.upload_service.app:app", "--bind", "0.0.0.0:8001", "--workers", "4"]