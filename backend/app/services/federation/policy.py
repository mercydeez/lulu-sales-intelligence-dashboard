"""
Role policy for federated Sage — decides which sources a caller may query and
how many rows they get. Consumers (embedded widget / public API key) get the
narrowest scope; admins get all the tenant's sources and cross-source merge.

Tenant isolation is enforced UNDER this by each adapter (GUC/tenant filter); this
layer only governs *source visibility* and result size by role.
"""
from __future__ import annotations

from .base import SourceDescriptor

# Higher rank = more access. 'consumer' is the public-API/embed caller.
ROLE_RANK = {
    "consumer": 0,
    "store_manager": 1,
    "regional_manager": 2,
    "admin": 3,
    "super_admin": 4,
}


def rank(role: str) -> int:
    return ROLE_RANK.get(role or "consumer", 0)


def can_use_source(role: str, descriptor: SourceDescriptor) -> bool:
    """A role may query a source if its rank meets the source's minimum."""
    return rank(role) >= rank(descriptor.min_role)


def max_rows_for(role: str) -> int:
    """Result cap by role — consumers get small payloads, admins get more."""
    return 50 if rank(role) <= ROLE_RANK["store_manager"] else 200


def allow_cross_source_merge(role: str) -> bool:
    """Only regional+ may merge/compare across multiple sources; consumers get a
    single best source to keep answers simple and payloads small."""
    return rank(role) >= ROLE_RANK["regional_manager"]
