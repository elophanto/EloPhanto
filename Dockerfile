# EloPhanto Cloud — Production Dockerfile
# Per-user isolated container with full agent + browser + dashboard

FROM python:3.12-slim AS base

# System dependencies: Chrome, Node.js, fonts
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    gnupg \
    git \
    # Chrome dependencies
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2t64 \
    libpango-1.0-0 \
    libcairo2 \
    # Fonts for browser rendering
    fonts-liberation \
    fonts-noto-color-emoji \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 (for browser bridge)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv for fast Python dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# ---------- Python dependencies ----------
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev

# ---------- Browser bridge ----------
COPY bridge/browser/package.json bridge/browser/package-lock.json bridge/browser/
RUN cd bridge/browser && npm ci

COPY bridge/browser/tsconfig.json bridge/browser/tsup.config.ts bridge/browser/
COPY bridge/browser/src/ bridge/browser/src/
RUN cd bridge/browser && npm run build && npm prune --omit=dev

# ---------- Web dashboard (built from source) ----------
COPY web/package.json web/package-lock.json web/components.json web/postcss.config.mjs web/
COPY web/index.html web/tsconfig*.json web/vite.config.ts web/
COPY web/public/ web/public/
COPY web/src/ web/src/
RUN cd web && npm ci && npm run build

# ---------- Application code ----------
COPY core/ core/
COPY tools/ tools/
COPY cli/ cli/
COPY channels/ channels/
COPY knowledge/ knowledge/
COPY plugins/ plugins/
COPY skills/ skills/

# ---------- Playwright browser install ----------
RUN uv run playwright install chromium --with-deps

# ---------- Data volume ----------
# /data is mounted as a persistent Fly volume
# Contains: vault.enc, vault.salt, data/*.db, knowledge/, config.yaml
VOLUME /data

# ---------- Environment ----------
ENV PYTHONUNBUFFERED=1
ENV ELOPHANTO_CONFIG=/data/config.yaml
ENV ELOPHANTO_CLOUD=1

# Gateway port
EXPOSE 18789

# Health check — gateway WebSocket responds
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:18789/health || exit 1

# Entrypoint: start gateway bound to all interfaces
CMD ["uv", "run", "python", "-m", "cli.main", "gateway"]
