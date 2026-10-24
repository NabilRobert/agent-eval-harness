# The harness, for on-demand runs on the VPS (ADR-008). Every version is
# exact, and base images are pinned by multi-arch digest, so a re-pushed tag
# can never change them. Keys are never in the image: they come from an env file at run time.

# Stage 1: the pinned filesystem MCP server, installed from its lockfile.
FROM node:22.23.3-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9 AS fs-server
WORKDIR /fs
COPY tools/fs-server/package.json tools/fs-server/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund

# Stage 2: Python + the node binary + the harness.
FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
COPY --from=fs-server /usr/local/bin/node /usr/local/bin/node
# The run user's uid matches the host user who owns the mounted runs/
# folder (ubuntu = 1000 on the VPS), so run records can be written.
ARG HARNESS_UID=1000
RUN pip install --no-cache-dir uv==0.13.1 \
 && useradd --create-home --uid "$HARNESS_UID" harness
WORKDIR /app
# Dependencies first, in their own layer: a code change doesn't re-download them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY agent_eval/ agent_eval/
RUN uv sync --frozen --no-dev
COPY suites/ suites/
COPY prices.yaml results.yaml ./
COPY --from=fs-server /fs/node_modules tools/fs-server/node_modules
# COPY keeps the host's file modes. A checkout where files are 600 (the
# VPS had some) would leave them unreadable to the non-root run user, so
# everything is made readable here, whatever the host had.
RUN chmod -R a+rX /app \
 && mkdir -p runs .inspect-logs && chown harness runs .inspect-logs

# No .git in the image, so the commit it was built from is stamped in at
# build time: full runs refuse an unknown or dirty one (clean-tree guard).
ARG HARNESS_GIT=unknown
ENV AGENT_EVAL_HARNESS_GIT=$HARNESS_GIT \
    PATH="/app/.venv/bin:$PATH" \
    HOME=/tmp \
    INSPECT_DISPLAY=none
USER harness
ENTRYPOINT ["agent-eval"]
