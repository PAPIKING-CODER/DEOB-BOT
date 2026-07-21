FROM python:3.12-slim

# Lua 5.1 (motor de Prometheus-DeobfuscatorV2) + git para clonar sus dependencias
RUN apt-get update && apt-get install -y --no-install-recommends \
    lua5.1 \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# --- Deobfuscador V2 (motor principal, en Lua) ---
# Se clona en build time para no tener que subir cientos de archivos a mano.
RUN git clone --depth 1 https://github.com/0x251/Prometheus-DeobfuscatorV2.git /app/deobv2 \
    && git clone --depth 1 https://github.com/wcrddn/Prometheus.git /app/deobv2/Prometheus

# --- Dependencias de Python ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Tu bot (incluye pol.py / modules/ como fallback V1) ---
COPY . .

CMD ["python", "bot.py"]
