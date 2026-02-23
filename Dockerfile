FROM python:3.11-slim

WORKDIR /app

# Copy project metadata and source together (pip install needs both)
COPY pyproject.toml .
COPY src/ src/

# Install the package and all dependencies
RUN pip install --no-cache-dir .

# Create data directory (Railway Volume should be mounted here)
RUN mkdir -p /app/data

CMD ["python", "-m", "src.main"]
