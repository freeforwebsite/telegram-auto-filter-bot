FROM python:3.11-slim

WORKDIR /app

# Install necessary packages
RUN apt-get update && apt-get install -y ffmpeg gcc && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose Hugging Face default port
EXPOSE 7860
ENV PORT=7860

# Run the bot
CMD ["python", "bot.py"]
