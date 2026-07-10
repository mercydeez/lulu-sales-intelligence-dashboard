"""E6-5 — 100 concurrent SSE consumers on /stream/sales.

k6 has no EventSource and no streaming-response API, so it cannot measure this
surface at all. Rather than quietly leave SSE out of the "100 concurrent users"
claim, it is measured here, separately, and reported separately.

What is measured, per connection:
  * did it establish (HTTP 200 with text/event-stream);
  * time to the FIRST event — the number a user actually feels, because the
    dashboard renders nothing until one arrives;
  * events received during the hold window.

What is NOT measured: throughput of the generator. It emits a sale every 5–15s by
design, so the event rate is a property of the generator, not of the server's
capacity to fan out. A soak that "achieved" 2 events/sec would only mean the
generator was reconfigured.

Usage:
    python loadtest/sse_soak.py --connections 100 --hold 60
"""
from __future__ import annotations

import argparse
import asyncio
import statistics
import time
from typing import List, Optional

import httpx

DEFAULT_BASE = "http://localhost:8000"
DEFAULT_EMAIL = "atharva@retaildemo.app"
DEFAULT_PASSWORD = "Demo@2026!"


class Result:
    __slots__ = ("connected", "first_event_s", "events", "error")

    def __init__(self) -> None:
        self.connected = False
        self.first_event_s: Optional[float] = None
        self.events = 0
        self.error: Optional[str] = None


async def login_and_get_ticket(base: str, email: str, password: str) -> str:
    """SSE does not authenticate by cookie.

    `/stream/sales` takes a short-lived signed *ticket* on the query string —
    EventSource cannot set an Authorization header, and riding the session cookie
    on a long-lived stream would widen its exposure.

    Getting one means walking the real browser flow:
      1. any safe request issues the `csrf_token` cookie;
      2. state-changing requests echo it back in `X-CSRF-Token` (double submit);
      3. POST /api/auth/login, then POST /api/auth/stream-ticket.
    """
    async with httpx.AsyncClient(timeout=30.0) as c:
        await c.get(f"{base}/api/auth/me")            # issues the csrf cookie
        csrf = c.cookies.get("csrf_token")
        if not csrf:
            raise RuntimeError("no csrf_token cookie issued — did the middleware change?")
        headers = {"X-CSRF-Token": csrf}

        r = await c.post(f"{base}/api/auth/login",
                         json={"email": email, "password": password}, headers=headers)
        r.raise_for_status()

        t = await c.post(f"{base}/api/auth/stream-ticket", headers=headers)
        t.raise_for_status()
        body = t.json()
        ticket = body.get("ticket") or body.get("stream_ticket") or body.get("token")
        if not ticket:
            raise RuntimeError(f"no ticket in /stream-ticket response: {list(body)}")
        return ticket


async def one_consumer(base: str, ticket: str, hold: float, started: asyncio.Event) -> Result:
    res = Result()
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None)) as c:
            async with c.stream("GET", f"{base}/stream/sales", params={"ticket": ticket}) as resp:
                if resp.status_code != 200:
                    res.error = f"HTTP {resp.status_code}"
                    return res
                res.connected = True
                started.set()
                deadline = time.perf_counter() + hold
                async for line in resp.aiter_lines():
                    if time.perf_counter() > deadline:
                        break
                    if line.startswith("data:"):
                        if res.first_event_s is None:
                            res.first_event_s = time.perf_counter() - t0
                        res.events += 1
    except Exception as exc:
        res.error = f"{type(exc).__name__}: {exc}"
    return res


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--connections", type=int, default=100)
    p.add_argument("--hold", type=float, default=60.0)
    p.add_argument("--email", default=DEFAULT_EMAIL)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    args = p.parse_args()

    print(f"logging in as {args.email} and minting an SSE ticket …")
    ticket = await login_and_get_ticket(args.base, args.email, args.password)

    print(f"opening {args.connections} SSE connections, holding {args.hold:.0f}s …")
    started = asyncio.Event()
    t0 = time.perf_counter()

    async def bounded() -> Result:
        # `aiter_lines` only wakes when a line arrives, so the in-loop deadline
        # cannot fire on a silent connection. Bound the whole consumer instead, or
        # a stream that never emits would hang the soak indefinitely.
        try:
            return await asyncio.wait_for(
                one_consumer(args.base, ticket, args.hold, started),
                timeout=args.hold + 15.0,
            )
        except asyncio.TimeoutError:
            r = Result()
            r.error = "timeout waiting for stream to close"
            return r

    results: List[Result] = await asyncio.gather(*(bounded() for _ in range(args.connections)))
    elapsed = time.perf_counter() - t0

    ok = [r for r in results if r.connected]
    failed = [r for r in results if not r.connected]
    with_event = [r for r in ok if r.first_event_s is not None]
    firsts = sorted(r.first_event_s for r in with_event)
    total_events = sum(r.events for r in ok)

    def pct(xs, q):
        if not xs:
            return None
        i = min(len(xs) - 1, int(round((q / 100.0) * (len(xs) - 1))))
        return xs[i]

    print("\n--- SSE soak result ---")
    print(f"  connections requested : {args.connections}")
    print(f"  established           : {len(ok)}")
    print(f"  failed                : {len(failed)}")
    if failed:
        reasons = {}
        for r in failed:
            reasons[r.error] = reasons.get(r.error, 0) + 1
        for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
            print(f"      {n:>4} x {reason}")
    print(f"  received >=1 event    : {len(with_event)}")
    if firsts:
        print(f"  first-event latency   : p50 {pct(firsts,50):.2f}s  "
              f"p95 {pct(firsts,95):.2f}s  max {firsts[-1]:.2f}s")
    print(f"  total events delivered: {total_events}")
    print(f"  wall clock            : {elapsed:.1f}s")
    print("\n  NOTE: event rate reflects the generator's 5-15s cadence, not server capacity.")


if __name__ == "__main__":
    asyncio.run(main())
