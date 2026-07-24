FROM python:3.13-slim-bookworm

ARG PLAYWRIGHT_VERSION=1.61.1

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_MODULE=/opt/report-node/node_modules/playwright

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm unzip fonts-noto-cjk \
    && python -m pip install --no-cache-dir "PyMuPDF>=1.24,<2" \
    && mkdir -p /opt/report-node \
    && npm install --prefix /opt/report-node "playwright@${PLAYWRIGHT_VERSION}" \
    && /opt/report-node/node_modules/.bin/playwright install --with-deps chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /work

CMD ["python", "--version"]
