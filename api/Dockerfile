FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

# Snelle/kleine installs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Tooling needed for healthchecks/debugging
RUN apt-get update \
    && apt-get install --no-install-recommends -y curl \
    && rm -rf /var/lib/apt/lists/*

# Dependencies via uv
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen

# App code
COPY . /app

# Run
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "src.pixie_tabular_api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
