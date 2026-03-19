FROM python:3.10-slim

# Install HandBrake CLI and update system
RUN apt-get update && \
    apt-get install -y handbrake-cli && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your code
COPY . .

# Run the bot
CMD ["python", "bot.py"]
