"""Long-running: the ONE process that hosts every continuous singleton.

    python -m app.commands.singletons

WHY THIS EXISTS.
These loops must run in exactly one process, and each was previously started from
the API's ASGI lifespan — which meant `gunicorn --workers N` would run N of each:
N synthetic-sale generators (N× the demo write rate), N concurrent partition
`DROP TABLE`s on the same table, N nightly demo wipes. Moving them here makes
"exactly one" a DEPLOYMENT fact — this command runs in a single-replica container
(`replicas: 1` in both compose files) — instead of a runtime leader election that
could silently fail over, split-brain, or be invisible at 3am.

The API process now runs NONE of these; it keeps only `import_scheduler`, which is
already safe across processes via `FOR UPDATE SKIP LOCKED`.

Each loop is flag-gated exactly as it was in the lifespan, so nothing new runs by
default and disabling a feature still disables it. A Redis heartbeat
(`health:worker:singletons`) lets the API's /health surface this container being
dead as a loud degradation rather than silence.

Exit codes: 0 clean stop (SIGTERM/SIGINT) / 1 on error.
"""
from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime, timezone

from app.config import get_settings, logger
from app.services.database import init_db, close_db
from app.services.redis_client import init_redis, close_redis

SINGLETONS_HEARTBEAT_KEY = "health:worker:singletons"
_HEARTBEAT_INTERVAL_SECONDS = 30


async def _emit_heartbeat(started: list[str]) -> None:
    """Best-effort heartbeat; a Redis blip must never kill the singletons."""
    from app.services import redis_client as _redis
    client = _redis.redis_client
    if client is None:
        return
    payload = {
        "service": "singletons",
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "loops": started,
    }
    ttl = max(_HEARTBEAT_INTERVAL_SECONDS * 2, get_settings().worker_heartbeat_stale_seconds)
    try:
        await client.set(SINGLETONS_HEARTBEAT_KEY, json.dumps(payload), ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[singletons] heartbeat write failed: {exc}")


async def _heartbeat_loop(started: list[str], stop: asyncio.Event) -> None:
    while not stop.is_set():
        await _emit_heartbeat(started)
        try:
            await asyncio.wait_for(stop.wait(), timeout=_HEARTBEAT_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


async def _main() -> int:
    settings = get_settings()
    logger.info("[singletons] starting — the single home for continuous background loops")

    await init_db()
    await init_redis()

    tasks: list[tuple[str, asyncio.Task]] = []
    started: list[str] = []

    def _track(name: str, coro) -> None:
        task = asyncio.create_task(coro, name=name)

        def _on_done(t: asyncio.Task) -> None:
            if t.cancelled():
                return
            exc = t.exception()
            if exc is not None:
                logger.error(f"[singletons] loop '{name}' crashed: {exc!r}")

        task.add_done_callback(_on_done)
        tasks.append((name, task))
        started.append(name)
        logger.info(f"[singletons] started loop: {name}")

    # The synthetic generator writes fake sales — DEMO ONLY. Same gating and E0-8
    # self-confinement as the old lifespan block; here it simply runs in exactly
    # one process instead of one-per-web-worker.
    if settings.demo_mode and settings.live_generator_enabled:
        from app.services.data_generator import DataGenerator
        _track("data_generator", DataGenerator().start())
    else:
        logger.info("[singletons] data_generator NOT started (demo/live-generator disabled)")

    if settings.demo_mode and settings.demo_reset_enabled:
        from app.services.demo_reset import run_demo_reset_loop
        _track("demo_reset", run_demo_reset_loop())

    if settings.run_cache_warmer:
        from app.services.cache_warmer import run_cache_warmer
        _track("cache_warmer", run_cache_warmer())

    if settings.run_forecast_trainer:
        from app.services.forecast_trainer import run_forecast_trainer
        _track("forecast_trainer", run_forecast_trainer())

    # E6-3: create-months-ahead + drop-past-retention. Single-instance here, so the
    # concurrent-DDL race that made it unsafe across web workers cannot occur.
    if settings.partition_maintenance_enabled:
        from app.services.partition_maintenance import partition_maintenance_loop
        _track("partition_maintenance", partition_maintenance_loop())

    # E2-1: pull connected POS vendors nightly into the basket grain. Inert with no
    # connections; single-instance here so a tenant's receipts aren't pulled N times.
    if settings.pos_sync_enabled:
        from app.services.pos_connectors import pos_sync_loop
        _track("pos_sync", pos_sync_loop())

    # HORIZON 1: recompute every campaign's incrementality readout on a schedule.
    #
    # This is what closes the loop. `measurement.measure()` has computed
    # treatment-vs-control correctly for a while, but nothing ran it and nothing
    # kept the answer — the product could measure lift and could not learn from
    # it. Each pass writes an immutable row to `flywheel_readouts` with an
    # anytime-valid confidence interval attached.
    #
    # Lives HERE and not in the API lifespan for the reason stated at the top of
    # this file: under `gunicorn --workers N` the API is N processes, and a
    # scheduler started there would run N times. Readouts are idempotent per
    # (campaign, window_end) so duplicate passes would be harmless rather than
    # corrupting — but harmless waste is still waste, and single-instance is the
    # honest home for a continuous loop.
    if settings.flywheel_readout_scheduler_enabled:
        from app.services.database import async_session
        from app.services.flywheel.readout import scheduler_loop as flywheel_readout_loop
        _track("flywheel_readouts",
               flywheel_readout_loop(async_session,
                                     tenant_id=settings.demo_tenant_id))
    else:
        logger.info("[singletons] flywheel_readouts NOT started "
                    "(FLYWHEEL_READOUT_SCHEDULER_ENABLED=false)")

    # HORIZON 2: the durable job worker. Processes flywheel_jobs (scoring,
    # measurement, shadow passes) with a lease + checkpoint so a mid-run crash is
    # resumed rather than lost. Runs here as a single instance for the same reason
    # as the readout scheduler — but note it is safe to run in every API worker
    # too, because claims use FOR UPDATE SKIP LOCKED. The reaper inside the loop
    # reclaims jobs stranded by a dead worker, which is the whole point of the
    # tier: a redeploy mid-scoring costs one batch, not the run.
    if settings.flywheel_job_worker_enabled:
        from app.services.database import async_session
        from app.services.flywheel.jobs import worker_loop as flywheel_job_worker
        import socket
        worker_id = f"singletons-{socket.gethostname()}"
        _track("flywheel_jobs",
               flywheel_job_worker(async_session, worker_id=worker_id))
    else:
        logger.info("[singletons] flywheel_jobs worker NOT started "
                    "(FLYWHEEL_JOB_WORKER_ENABLED=false)")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # pragma: no cover - non-unix
            pass

    if not tasks:
        # No loops enabled by config (partition_maintenance + cache_warmer default
        # ON everywhere, so this only happens if an operator disables everything).
        # Idle on the stop signal rather than exiting: a clean exit under
        # `restart: unless-stopped` would spin the container in a restart loop.
        logger.warning("[singletons] no loops enabled by config — idling until stopped")
        await stop.wait()
        await close_redis()
        await close_db()
        logger.info("[singletons] stopped")
        return 0

    hb = asyncio.create_task(_heartbeat_loop(started, stop), name="heartbeat")
    logger.info(f"[singletons] running {len(tasks)} loop(s): {started}")

    rc = 0
    try:
        from app.services.data_generator import DemoScopeError

        stop_task = asyncio.create_task(stop.wait())
        live = {name: t for name, t in tasks}

        # Supervise until a signal stops us or a loop genuinely CRASHES.
        #
        # The distinction that matters: a crash (DB gone, bug, unhandled error)
        # is transient, so we exit non-zero and let `restart: always` recreate us
        # clean. An ENVIRONMENT REFUSAL is not. DemoScopeError means the demo
        # tenant owns no stores or items, so the generator is correctly refusing
        # to invent synthetic sales with nothing safe to write to (the E0-8
        # guard). On a production box that is PERMANENTLY true — production ships
        # without demo data by design — so restarting can never help.
        #
        # An earlier version exited as soon as ANY loop finished, which meant one
        # declining loop tore down the other five healthy ones and the container
        # restart-looped forever. We now drop the decliner and keep supervising
        # the rest.
        while live and not stop.is_set():
            done, _pending = await asyncio.wait(
                [stop_task] + list(live.values()),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if stop.is_set():
                break

            crashed = False
            for name, t in list(live.items()):
                if not (t.done() and not t.cancelled()):
                    continue
                exc = t.exception()
                del live[name]
                if exc is None:
                    logger.info(f"[singletons] loop '{name}' completed and exited.")
                elif isinstance(exc, DemoScopeError):
                    logger.warning(
                        f"[singletons] loop '{name}' cannot run in this "
                        f"environment and is disabled: {exc} "
                        f"Other loops continue."
                    )
                else:
                    logger.error(f"[singletons] exiting because loop '{name}' failed: {exc!r}")
                    rc = 1
                    crashed = True
            if crashed:
                break

        # Every loop declined or finished, and nothing crashed. PARK rather than
        # exit: `restart: always` would otherwise recreate the container in a
        # quiet but endless loop. Staying up idle is the honest state — there is
        # nothing to supervise here, and a later data import plus a restart will
        # bring the loops back.
        if rc == 0 and not live and not stop.is_set():
            logger.warning(
                "[singletons] no loop can run in this environment "
                "(production ships without demo data). Idling — "
                "restart this container after importing data to re-evaluate."
            )
            await stop.wait()

    finally:
        stop.set()
        for _name, t in tasks:
            t.cancel()
        hb.cancel()
        for _name, t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await close_redis()
        await close_db()
        logger.info("[singletons] stopped")
    return rc


def main() -> None:
    import sys
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
