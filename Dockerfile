FROM python:3.11-slim

# System deps for Pillow + fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6-dev libjpeg-dev libpng-dev libwebp-dev zlib1g-dev \
    fonts-dejavu-core fonts-liberation wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Pre-download fonts at build time
RUN python -c "from generator.utils import setup_fonts; setup_fonts()" 2>/dev/null || true

EXPOSE 8080
CMD ["python", "bot.py"]
