# Runbook: harness runs on the VPS

The harness runs **on demand** in its own container (ADR-008). It's started
for a run and exits when the run ends. No service, no scheduler, no public
way to start a run. It shares the VPS with MCP-backbone, so the container is
capped at 1 CPU and 1 GB, and reaches MCP-backbone only through
`https://mcp.my.id/mcp/`, like any outside client.

## One-time setup

```bash
git clone https://github.com/NabilRobert/agent-eval-harness ~/agent-eval-harness
```

**The key file** lives outside the repo, mode 600. Edit it with a terminal
editor (`nano`), not VS Code: VS Code keeps local-history copies of edited
files, which is how a key ended up in a stray file once before.

```bash
mkdir -p ~/.config/agent-eval
install -m 600 /dev/null ~/.config/agent-eval/env
nano ~/.config/agent-eval/env
```

It needs three lines:

```
SUMOPOD_AI_API_KEY=...
SUMOPOD_BASE_URL=...
MCP_BACKBONE_EVAL_KEY=...
```

## Build (after every pull)

```bash
cd ~/agent-eval-harness && git pull
HARNESS_GIT=$(git describe --always --dirty --abbrev=12) docker compose -f deploy/compose.yaml build
```

The image records the commit it was built from. A full run refuses an
image built from a checkout with local edits.

## Run

Always check the plan first; it spends nothing:

```bash
docker compose -f deploy/compose.yaml run --rm harness run --plan-only
```

A smoke run:

```bash
docker compose -f deploy/compose.yaml run --rm harness run --suite suites/filesystem.yaml --tasks f01,f17 --epochs 1 --run-id vps-smoke
```

A full run (asks nothing, spends money: plan first):

```bash
docker compose -f deploy/compose.yaml run --rm harness run --suite suites/filesystem.yaml --run-id <id>
```

Run records land in `~/agent-eval-harness/runs/<id>/`.

## Publish a run

Run records are committed from the laptop, never from the VPS (the VPS
holds no GitHub credentials):

```bash
scp -r ubuntu@43.134.28.228:~/agent-eval-harness/runs/<id> runs/
uv run agent-eval report runs/<id> --check
git add runs/<id> && git commit -m "feat: <id> run"
```

To publish it, add it to `results.yaml` and run `uv run agent-eval publish`.

## Check and clean up

```bash
docker stats --no-stream                            # during a run: CPU and memory against the limits
docker compose -f deploy/compose.yaml down -v       # removes the raw-log volume
docker image prune -f                               # old images after rebuilds
```

**Rotating a key:** for the eval key, issue a new one in MCP-backbone's
console (Keys → Issue a new key). Update `~/.config/agent-eval/env` with
`nano`. Nothing else needs to change.
