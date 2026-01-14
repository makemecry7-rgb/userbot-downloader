FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && apt-get install -y \
    ffmpeg \
    aria2 \
    wget \
    ca-certificates \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# ===== MEGATOOLS =====
RUN apt-get update && apt-get install -y megatools && rm -rf /var/lib/apt/lists/*

# ===== MEGA-CMD (OFFICIAL WAY) =====
RUN wget -qO - https://mega.nz/linux/repo/Debian_11/Release.key | gpg --dearmor > /usr/share/keyrings/mega.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/mega.gpg] https://mega.nz/linux/repo/Debian_11/ ./" > /etc/apt/sources.list.d/mega.list \
 && apt-get update \
 && apt-get install -y megacmd \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
