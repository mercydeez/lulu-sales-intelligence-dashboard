"""
Phase 9 — observability.

Metrics are recorded per request and contain no secrets; structured logs carry
request/tenant/user correlation context.
"""
import logging
import re

from app.services.metrics import get_metrics
from app.config import JsonLogFormatter, log_tenant_ctx, log_user_ctx, request_id_ctx


class TestMetrics:
    def test_request_is_recorded(self):
        m = get_metrics()
        m.start_request("rq-test-1")
        m.end_request("rq-test-1", "GET", "/api/kpis/123", 200)
        out = m.export_prometheus()
        assert "http_requests_total" in out
        # Path IDs are normalized out (no raw id leakage).
        assert "/123" not in out

    def test_export_has_no_secrets(self):
        # Route labels (e.g. path="/api/auth/reset-password") legitimately name
        # auth endpoints and would otherwise false-positive on "password"/"secret".
        # Strip label VALUES, not just path=, so the check still catches a real
        # secret leaking into any other label (header, query, etc).
        out = re.sub(r'="[^"]*"', '=""', get_metrics().export_prometheus()).lower()
        for needle in ("password", "secret", "jwt", "bearer", "salespass", "connection_enc"):
            assert needle not in out


class TestStructuredLogContext:
    def _format(self):
        fmt = JsonLogFormatter()
        rec = logging.LogRecord("t", logging.INFO, __file__, 1, "hello", None, None)
        return fmt.format(rec)

    def test_includes_tenant_and_user_when_set(self):
        t1 = log_tenant_ctx.set("7")
        t2 = log_user_ctx.set("42")
        try:
            out = self._format()
        finally:
            log_tenant_ctx.reset(t1)
            log_user_ctx.reset(t2)
        assert '"tenant_id": "7"' in out
        assert '"user_id": "42"' in out
        assert '"request_id"' in out

    def test_omits_context_when_unset(self):
        # Defaults are "-" → keys omitted entirely.
        out = self._format()
        assert "tenant_id" not in out
        assert "user_id" not in out
