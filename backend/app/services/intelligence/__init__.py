"""
Proactive intelligence — Foresia's "what's going wrong / about to go wrong" layer.

Risk scans run on a schedule (triggered by the BullMQ worker) and persist ranked,
deduped findings to `risk_findings`. The dashboard Risk Radar and Sage read them.
"""
from .risk_scans import run_scan, run_scan_all_tenants, SCAN_TYPES

__all__ = ["run_scan", "run_scan_all_tenants", "SCAN_TYPES"]
