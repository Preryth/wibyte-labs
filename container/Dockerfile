FROM python:3.12-slim

WORKDIR /workspace

RUN useradd --create-home --shell /bin/bash student \
    && chown -R student:student /workspace

USER student

CMD ["bash"]