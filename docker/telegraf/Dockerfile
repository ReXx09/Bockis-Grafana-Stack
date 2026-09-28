FROM telegraf:1.34

RUN apt-get update \
    && apt-get install -y --no-install-recommends smartmontools \
    && rm -rf /var/lib/apt/lists/*