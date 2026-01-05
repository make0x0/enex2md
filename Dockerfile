FROM python:3.10-slim

WORKDIR /app

# Install system dependencies
# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    tesseract-ocr \
    tesseract-ocr-jpn \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libjpeg-dev \
    libopenjp2-7-dev \
    libffi-dev \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Download 3rd party assets (compliance: do not include in repo)
# distinct location to avoid volume mount overwrite issues
RUN mkdir -p /opt/enex2md/assets && \
    curl -L -o /opt/enex2md/assets/crypto-js.min.js https://cdnjs.cloudflare.com/ajax/libs/crypto-js/4.1.1/crypto-js.min.js

# Set entrypoint (can be overridden by docker-compose or command line)
ENTRYPOINT ["python", "enex2all.py"]
