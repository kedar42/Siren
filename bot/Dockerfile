FROM python:3.12-slim

WORKDIR /app

# ffmpeg streams + transcodes audio for discord.py's native voice client.
# libopus is what discord.py links against to encode the Opus frames it sends
# to Discord; on slim it isn't pulled in by ffmpeg's deps so we install it
# explicitly.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "-u", "main.py"]
