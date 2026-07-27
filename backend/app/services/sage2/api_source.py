"""
External API source for Sage v2 (S4) — call a third-party REST feed for a
sub-question (weather, FX, market/competitor prices, …) and return a grounded
value. Config-driven via settings.external_api_sources (JSON); empty => no API
intents exist, so it's a pure no-op until you provide endpoints/keys.

Each configured source: {keyword, url, value_path (dotted), header_env?, header_name?}.
The value is read straight from the JSON response at value_path — never invented;
if the call fails or the path is missing, the sub-answer reports that.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.config import get_settings

logger = logging.getLogger(__name__)


@dataclass
class ApiSource:
    name: str
    keyword: str
    url: str
    value_path: str
    header_env: Optional[str] = None
    header_name: Optional[str] = None


def load_sources() -> List[ApiSource]:
    raw = (get_settings().external_api_sources or "").strip()
    if not raw:
        return []
    try:
        cfg: Dict[str, dict] = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("external_api_sources is not valid JSON; ignoring")
        return []
    out: List[ApiSource] = []
    for name, s in cfg.items():
        if s.get("url") and s.get("value_path") and s.get("keyword"):
            out.append(ApiSource(
                name=name, keyword=s["keyword"], url=s["url"], value_path=s["value_path"],
                header_env=s.get("header_env"), header_name=s.get("header_name"),
            ))
    return out


def is_safe_url(url: str) -> bool:
    """SSRF guard: only https/http to a PUBLIC host. Blocks non-http schemes
    (file://, gopher://) and private/loopback/link-local targets (cloud metadata
    169.254.169.254, localhost, RFC-1918). External API source URLs are
    operator-configured today, but this makes SSRF impossible even if a
    misconfig or a future tenant-supplied source slips a hostile URL through."""
    import ipaddress
    import socket
    from urllib.parse import urlparse
    try:
        u = urlparse(url)
        if u.scheme not in ("http", "https") or not u.hostname:
            return False
        # Resolve and reject any private / loopback / link-local / reserved IP.
        for fam, _, _, _, sockaddr in socket.getaddrinfo(u.hostname, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if (ip.is_private or ip.is_loopback or ip.is_link_local
                    or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
                return False
        return True
    except Exception:
        return False


def _dig(obj: Any, path: str) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


async def call_source(src: ApiSource) -> dict:
    """Fetch the source and extract value_path. Returns {ok, value|error, source}."""
    import httpx
    if not is_safe_url(src.url):
        return {"ok": False, "error": "source URL blocked (SSRF guard)", "source": src.name}
    headers = {}
    if src.header_env and src.header_name:
        key = os.environ.get(src.header_env)
        if key:
            headers[src.header_name] = key
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(src.url, headers=headers)
            r.raise_for_status()
            value = _dig(r.json(), src.value_path)
        if value is None:
            return {"ok": False, "error": f"value_path '{src.value_path}' not found", "source": src.name}
        return {"ok": True, "value": value, "source": src.name}
    except Exception as e:  # network / non-2xx / parse
        return {"ok": False, "error": str(e)[:200], "source": src.name}


def match_api_sources(question: str) -> List[ApiSource]:
    q = question.lower()
    return [s for s in load_sources() if s.keyword.lower() in q]
