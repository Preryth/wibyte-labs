FROM python:3.12-slim

WORKDIR /workspace

RUN apt-get update     && apt-get install -y --no-install-recommends         git         python3-tk         xvfb         fluxbox         x11vnc         x11-xserver-utils         xauth         xterm         novnc         websockify         procps     && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash student     && chown -R student:student /workspace

USER student

CMD ["bash"]
