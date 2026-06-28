# Versión de Java configurable en tiempo de build.
# Versiones disponibles en Debian Bookworm: 17, 21
# Uso: docker build --build-arg JAVA_VERSION=17 .
ARG JAVA_VERSION=21

FROM python:3.12-slim

ARG JAVA_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
        openjdk-${JAVA_VERSION}-jre-headless \
        iproute2 \
        procps \
        psmisc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV SERVERS_PATH=/servers \
    PYTHONUNBUFFERED=1

EXPOSE 8000 25565

CMD ["python", "main.py"]
