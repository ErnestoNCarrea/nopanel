# Multi-stage build for nopanel v2 container
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml READMEv2.md ./
COPY nopanel/ nopanel/
RUN pip install --no-cache-dir build==1.2.2.post1 && python -m build --wheel --outdir /wheels

FROM python:3.12-slim AS runtime

RUN groupadd -r nopanel && useradd -r -g nopanel -s /sbin/nologin nopanel

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Docker CLI for compose operations + MariaDB client for SQL via socket
RUN apt-get update && apt-get install -y --no-install-recommends docker.io mariadb-client && rm -rf /var/lib/apt/lists/*
# The Docker socket is mounted at runtime

VOLUME ["/etc/nopanel", "/var/log/nopanel"]

# noPanel needs access to the Docker socket for container management,
# self-signed cert generation (openssl), and writing to /etc/nopanel.
# System user management is delegated to the host administrator via
# generated commands (nopanel user host-commands / nopanel commit).
ENTRYPOINT ["nopanel"]
