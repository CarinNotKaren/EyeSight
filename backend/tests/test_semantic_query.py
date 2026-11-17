import pytest

from multimedia import semantic_query


def forbid_translation(*args, **kwargs):
    raise AssertionError("Translation must not be called.")


def test_english_bypasses_translation(monkeypatch):
    monkeypatch.setattr(
        semantic_query, "_translate_to_english", forbid_translation
    )

    original = "  a couch and chairs  "
    result = semantic_query.prepare_semantic_query(original, "en-US")

    assert result["original_query"] == original
    assert result["search_query"] == "a couch and chairs"
    assert result["translated"] is False
    assert result["translation_model"] is None


@pytest.mark.parametrize(
    "text, language",
    [
        ("", "en"),
        ("   ", "fr"),
        (None, "en"),
        ("x" * 2001, "ar"),
        ("example", "de"),
        ("example", None),
    ],
)
def test_invalid_input_rejected_without_translation(
    monkeypatch, text, language
):
    monkeypatch.setattr(
        semantic_query, "_translate_to_english", forbid_translation
    )

    with pytest.raises(ValueError):
        semantic_query.prepare_semantic_query(text, language)


def test_translation_preserves_original_and_records_model(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("VLM_MODEL", "team-model")
    monkeypatch.setenv("SEMANTIC_QUERY_MODEL", "translation-model")

    captured = {}

    def fake_translate(text, language, model_id, api_key):
        captured.update(
            text=text,
            language=language,
            model_id=model_id,
        )
        return "a sofa and chairs"

    monkeypatch.setattr(
        semantic_query, "_translate_to_english", fake_translate
    )

    original = "un canap\u00e9 et des chaises"
    result = semantic_query.prepare_semantic_query(original, "fr-FR")

    assert result["original_query"] == original
    assert result["search_query"] == "a sofa and chairs"
    assert result["source_language"] == "fr"
    assert result["search_language"] == "en"
    assert result["translated"] is True
    assert result["translation_model"] == "translation-model"
    assert captured["model_id"] == "translation-model"
    assert captured["language"] == "fr"
    assert captured["text"] == original


def test_missing_key_stops_before_translation(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("VLM_MODEL", "team-model")
    monkeypatch.setattr(
        semantic_query, "_translate_to_english", forbid_translation
    )

    with pytest.raises(
        semantic_query.QueryTranslationError, match="GEMINI_API_KEY"
    ):
        semantic_query.prepare_semantic_query("un fauteuil", "fr")


def test_translation_failure_has_no_silent_fallback(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("VLM_MODEL", "team-model")
    monkeypatch.delenv("SEMANTIC_QUERY_MODEL", raising=False)

    def fail_translation(*args, **kwargs):
        raise semantic_query.QueryTranslationError(
            "Simulated translation failure."
        )

    monkeypatch.setattr(
        semantic_query, "_translate_to_english", fail_translation
    )

    with pytest.raises(
        semantic_query.QueryTranslationError,
        match="Simulated translation failure",
    ):
        semantic_query.prepare_semantic_query("un fauteuil", "fr")
