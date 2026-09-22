import pytest

from src.core.exceptions import InternalServerError, ValidationError
from src.core.llm.langchain import providers
from src.core.llm.langchain.providers import anthropic, openai
from src.core.settings import settings


@pytest.fixture(autouse=True)
def api_keys(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "sk-ant-test")


def test_catalog_merges_every_provider():
    assert set(providers.CATALOG) == set(openai.CATALOG) | set(anthropic.CATALOG)


def test_no_model_name_is_claimed_by_two_providers():
    assert not set(openai.CATALOG) & set(anthropic.CATALOG)


def test_every_spec_has_a_builder():
    for spec in providers.CATALOG.values():
        assert spec.provider in providers.BUILDERS


def test_every_catalog_key_matches_its_spec_name():
    for name, spec in providers.CATALOG.items():
        assert name == spec.name


def test_available_models_is_sorted():
    assert providers.available_models() == sorted(providers.CATALOG)


def test_an_unknown_model_is_rejected():
    with pytest.raises(ValidationError) as exc:
        providers.spec_for("gpt-nonexistent")

    assert exc.value.code == "llm_model_not_available"
    assert exc.value.status_code == 422


def test_the_rejection_names_the_model():
    with pytest.raises(ValidationError) as exc:
        providers.spec_for("gpt-nonexistent")

    assert "gpt-nonexistent" in exc.value.message


def test_builds_an_openai_client():
    model = providers.build_model("gpt-4o")

    assert type(model).__name__ == "ChatOpenAI"
    assert model.model_name == "gpt-4o"


def test_builds_an_anthropic_client():
    model = providers.build_model("claude-sonnet-5")

    assert type(model).__name__ == "ChatAnthropic"
    assert model.model == "claude-sonnet-5"


def test_temperature_is_applied_when_the_model_accepts_it():
    model = providers.build_model("gpt-4o", temperature=0.9)

    assert model.temperature == 0.9


def test_temperature_is_omitted_when_the_model_rejects_it():
    model = providers.build_model("gpt-5.4", temperature=0.9)

    assert model.temperature != 0.9


def test_a_missing_openai_key_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    with pytest.raises(InternalServerError) as exc:
        providers.build_model("gpt-4o")

    assert exc.value.code == "llm_api_key_not_configured"


def test_a_missing_anthropic_key_is_reported(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)

    with pytest.raises(InternalServerError) as exc:
        providers.build_model("claude-sonnet-5")

    assert exc.value.code == "llm_api_key_not_configured"


def test_an_openai_model_never_reads_the_anthropic_key(monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)

    assert providers.build_model("gpt-4o") is not None


def test_an_anthropic_model_never_reads_the_openai_key(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)

    assert providers.build_model("claude-sonnet-5") is not None
