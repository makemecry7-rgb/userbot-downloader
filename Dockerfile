FROM python:3.10-slim

# ---------------- System deps ----------------
RUN apt-get update && \
    apt-get install -y \
        ffmpeg \
        aria2 \
        ca-certificates \
        gnupg \
        wget \
        lsb-release \
        megatools \
    && rm -rf /var/lib/apt/lists/*

# ---------------- Install mega-cmd (OFFICIAL APT REPO) ----------------
RUN wget -qO- https://mega.nz/linux/repo/Debian_11/Release.key | gpg --dearmor > /usr/share/keyrings/mega.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/mega.gpg] https://mega.nz/linux/repo/Debian_11/ ./" \
    > /etc/apt/sources.list.d/mega.list && \
    apt-get update && \
    apt-get install -y megacmd && \
    rm -rf /var/lib/apt/lists/*

# ---------------- App setup ----------------
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
