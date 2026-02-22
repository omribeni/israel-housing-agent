FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source code
COPY src/ src/

# Create data directory for SQLite (Railway Volume should be mounted here)
RUN mkdir -p /app/data

CMD ["python", "-m", "src.main"]
