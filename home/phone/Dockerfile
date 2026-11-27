FROM archlinux:latest
RUN pacman -Syu --noconfirm baresip python && pacman -Scc --noconfirm
COPY server.py /app/server.py
COPY baresip/config /app/baresip/config
CMD ["python3", "-u", "/app/server.py"]
