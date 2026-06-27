"""Container/CLI entrypoints for one-shot and background work.

In production the API process serves API only; the work below runs as dedicated
processes (see docker-compose.production.yml and docs/production/RUNTIME_PROCESSES.md):

    python -m app.commands.migrate            # one-shot: apply DB migrations
    python -m app.commands.seed               # one-shot: seed synthetic demo data (demo only)
    python -m app.commands.generator          # long-running: synthetic sale generator (demo only)
    python -m app.commands.cache_warmer       # long-running: dashboard cache warmer
    python -m app.commands.forecast_trainer   # long-running: offline forecast trainer

Each command logs clearly and exits non-zero on failure.
"""
