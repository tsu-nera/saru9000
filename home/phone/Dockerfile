FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends linphone-cli ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /var/lib/phone
COPY server.py linphonerc /app/
CMD ["python3", "-u", "/app/server.py"]
