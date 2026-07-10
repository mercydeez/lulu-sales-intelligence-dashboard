"""Bulk external-data ingestion (SCALE-2). See bulk.py and
docs/product/specs/EXTERNAL_DATA_AT_SCALE.md."""
from .bulk import ingest_csv_file, job_status, CHUNK_ROWS  # noqa: F401
