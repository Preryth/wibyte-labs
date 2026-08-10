FROM python:3.12-slim

WORKDIR /workspace

# Install Git and basic certificate support.
# These are installed as root before switching to
# the unprivileged student user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create the unprivileged student account.
RUN useradd --create-home --shell /bin/bash student \
    && chown -R student:student /workspace

USER student

CMD ["bash"]