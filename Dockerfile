# The harness, for on-demand runs on the VPS (ADR-008). Every version is
# exact. Keys are never in the image: they come from an env file at run time.

# Stage 1: the pinned filesystem MCP server, installed from its lockfile.
FROM node:22.23.3-bookworm-slim AS fs-server
WORKDIR /fs
COPY tools/fs-server/package.json tools/fs-server/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# Stage 2: Python + the node binary + the harness.
FROM python:3.12.12-slim-bookworm
COPY --from=fs-server /usr/local/bin/node /usr/local/bin/node
# The run user's uid matches the host user who owns the mounted runs/
# folder (ubuntu = 1000 on the VPS), so run records can be written.
ARG HARNESS_UID=1000
RUN pip install --no-cache-dir uv==0.13.1 \
 && useradd --create-home --uid "$HARNESS_UID" harness
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY agent_eval/ agent_eval/
RUN uv sync --frozen --no-dev
COPY suites/ suites/
COPY prices.yaml results.yaml ./
COPY --from=fs-server /fs/node_modules tools/fs-server/node_modules
RUN mkdir -p runs .inspect-logs && chown harness runs .inspect-logs

# No .git in the image, so the commit it was built from is stamped in at
# build time: full runs refuse an unknown or dirty one (clean-tree guard).
ARG HARNESS_GIT=unknown
ENV AGENT_EVAL_HARNESS_GIT=$HARNESS_GIT \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    INSPECT_DISPLAY=none
USER harness
ENTRYPOINT ["agent-eval"]
