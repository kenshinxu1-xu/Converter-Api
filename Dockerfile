FROM python:3.11-slim

# ffmpeg install — guaranteed!
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements_bot.txt .
RUN pip install --no-cache-dir -r requirements_bot.txt

COPY kenshin_converter_bot.py .

CMD ["python", "kenshin_converter_bot.py"]
