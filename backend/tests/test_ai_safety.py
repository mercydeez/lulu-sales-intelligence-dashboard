"""
Phase 11 — Sage AI production safety.

External AI is off unless explicitly enabled; the public API never returns raw SQL
in production; AI answers carry an evidence + demo-disclosure block. (The SQL guard
itself — SELECT-only, allow-listed views, tenant scope — is covered by
test_nl2sql_guard.py.)
"""
from unittest.mock import patch

from app.config import Settings


def _settings(**kw):
    base = dict(environment="testing",
                jwt_secret_key="test-secret-key-minimum-32-chars-long-for-testing",
                secret_key="test-app-secret-key-minimum-32-chars-for-testing")
    base.update(kw)
    return Settings(**base)


class TestExternalAIGating:
    def test_external_ai_excluded_by_default(self):
        import app.services.llm as llm
        s = _settings(openai_api_key="sk-fake", ollama_url="http://ollama:11434",
                      enable_external_ai=False, enable_local_ai=True)
        with patch.object(llm, "get_settings", return_value=s):
            chain = llm.get_provider_chain()
        assert not any(type(p).__name__ == "OpenAIProvider" for p in chain)
        assert any(type(p).__name__ == "OllamaProvider" for p in chain)

    def test_external_ai_included_when_enabled(self):
        import app.services.llm as llm
        s = _settings(openai_api_key="sk-fake", enable_external_ai=True)
        with patch.object(llm, "get_settings", return_value=s):
            chain = llm.get_provider_chain()
        assert any(type(p).__name__ == "OpenAIProvider" for p in chain)

    def test_local_ai_excluded_when_disabled(self):
        import app.services.llm as llm
        s = _settings(ollama_url="http://ollama:11434", enable_local_ai=False)
        with patch.object(llm, "get_settings", return_value=s):
            chain = llm.get_provider_chain()
        assert not any(type(p).__name__ == "OllamaProvider" for p in chain)


class TestPublicApiNoRawSql:
    def test_sql_hidden_in_production(self):
        import app.routes.public_api as papi
        with patch.object(papi, "get_settings", return_value=_settings(environment="production",
                          use_rls_role=True,
                          database_url="postgresql+asyncpg://u:str0ngp@db:5432/d")):
            assert papi._expose_sql() is False

    def test_sql_visible_in_development(self):
        import app.routes.public_api as papi
        with patch.object(papi, "get_settings", return_value=_settings(environment="development")):
            assert papi._expose_sql() is True


class TestAiEvidenceDisclosure:
    def test_demo_mode_discloses_synthetic_data(self):
        import app.routes.public_api as papi
        with patch.object(papi, "get_settings", return_value=_settings(demo_mode=True)):
            ev = papi._ai_evidence(tenant_id=3, row_count=5, grounded=True)
        assert ev["tenant_scope"] == 3
        assert "synthetic" in ev["data_disclosure"].lower() or "sample" in ev["data_disclosure"].lower()
        assert ev["confidence"] == "high"

    def test_real_mode_discloses_tenant_data(self):
        import app.routes.public_api as papi
        with patch.object(papi, "get_settings", return_value=_settings(
                environment="production", demo_mode=False, use_rls_role=True,
                database_url="postgresql+asyncpg://u:str0ngp@db:5432/d")):
            ev = papi._ai_evidence(tenant_id=3, row_count=0, grounded=False)
        assert "synthetic" not in ev["data_disclosure"].lower()
        assert ev["confidence"] == "low"
