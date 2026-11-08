import pytest
from pydantic import ValidationError

from app.api.ai_routes import ChatIn, SUPPORTED_LANGUAGES, _chat_url, _configured_providers


def test_chat_url_supports_openai_compatible_base_urls():
    assert _chat_url("https://provider.example/v1") == "https://provider.example/v1/chat/completions"
    assert _chat_url("https://provider.example/v1/chat/completions") == "https://provider.example/v1/chat/completions"


def test_ai_provider_registry_keeps_disabled_or_incomplete_providers_out(monkeypatch):
    from app.api import ai_routes
    monkeypatch.setattr(ai_routes.settings, "integration_ai_enabled", True)
    monkeypatch.setattr(ai_routes.settings, "ai_base_url", "https://primary.example/v1")
    monkeypatch.setattr(ai_routes.settings, "ai_api_key", "test-secret")
    monkeypatch.setattr(ai_routes.settings, "ai_model", "primary-model")
    monkeypatch.setattr(ai_routes.settings, "integration_ai_fallback_enabled", True)
    monkeypatch.setattr(ai_routes.settings, "ai_fallback_base_url", "")
    monkeypatch.setattr(ai_routes.settings, "ai_fallback_api_key", "fallback-secret")
    monkeypatch.setattr(ai_routes.settings, "ai_fallback_model", "fallback-model")
    providers = _configured_providers()
    assert len(providers) == 1
    assert providers[0]["name"] == "primary"
    assert providers[0]["model"] == "primary-model"
    assert providers[0]["api_key"] == "test-secret"


def test_ai_provider_registry_supports_primary_and_fallback(monkeypatch):
    from app.api import ai_routes
    for key, value in {
        "integration_ai_enabled": True, "ai_base_url": "https://primary.example/v1",
        "ai_api_key": "primary-secret", "ai_model": "primary-model",
        "integration_ai_fallback_enabled": True, "ai_fallback_base_url": "https://backup.example/v1",
        "ai_fallback_api_key": "backup-secret", "ai_fallback_model": "backup-model",
    }.items():
        monkeypatch.setattr(ai_routes.settings, key, value)
    providers = _configured_providers()
    assert [x["name"] for x in providers] == ["primary", "fallback"]


def test_chat_input_limits_prompt_and_restricts_task():
    with pytest.raises(ValidationError):
        ChatIn(prompt="")
    with pytest.raises(ValidationError):
        ChatIn(prompt="hello", task="run_sql")
    with pytest.raises(ValidationError):
        ChatIn(prompt="x" * 20001)
    assert ChatIn(prompt="Habari", language="sw").language == "sw"


def test_supported_language_set_includes_required_african_languages():
    assert {"en", "sw", "fr", "ar", "so", "am", "ha", "yo", "zu", "pt"} <= SUPPORTED_LANGUAGES

from fastapi import HTTPException
from app.api.ai_routes import _extract_upload


def test_ai_file_extraction_supports_text_and_csv():
    assert "quarter, revenue" in _extract_upload("report.csv", b"quarter,revenue\nQ1,100")
    assert "Project notes" in _extract_upload("notes.txt", b"Project notes")


def test_ai_file_extraction_rejects_unknown_and_mismatched_file_types():
    with pytest.raises(HTTPException) as exc:
        _extract_upload("payload.exe", b"hello")
    assert exc.value.status_code == 415
    with pytest.raises(HTTPException) as exc:
        _extract_upload("fake.pdf", b"not a pdf")
    assert exc.value.status_code == 415


def test_ai_file_extraction_enforces_size_and_nonempty_content():
    with pytest.raises(HTTPException) as exc:
        _extract_upload("large.txt", b"x" * (5 * 1024 * 1024 + 1))
    assert exc.value.status_code == 413
    with pytest.raises(HTTPException) as exc:
        _extract_upload("empty.txt", b"   ")
    assert exc.value.status_code == 422
