import base64
import importlib
import sys
import types
from unittest.mock import Mock

import pytest

import llm


@pytest.fixture(autouse=True)
def reset_llm_singleton(monkeypatch):
    monkeypatch.setattr(llm, "_llm_client_instance", None)


@pytest.mark.parametrize(
    ("provider", "key_name", "client_name"),
    [
        ("anthropic", "ANTHROPIC_API_KEY", "AnthropicLLM"),
        ("openai", "OPENAI_API_KEY", "OpenAILLM"),
        ("gemini", "GEMINI_API_KEY", "GeminiLLM"),
    ],
)
def test_factory_builds_selected_provider_at_runtime(
    monkeypatch, provider, key_name, client_name
):
    client = object()
    constructor = Mock(return_value=client)
    monkeypatch.setattr(llm, "LLM_PROVIDER", provider)
    monkeypatch.setattr(llm, key_name, "test-key")
    monkeypatch.setattr(llm, client_name, constructor)

    assert llm.get_llm_client() is client
    assert llm.get_llm_client() is client
    constructor.assert_called_once_with(api_key="test-key")


@pytest.mark.parametrize("key", [None, "", "sk-xxxxxxxx"])
def test_factory_rejects_missing_or_example_key(monkeypatch, key):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", key)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.get_llm_client()


def test_factory_rejects_unknown_provider(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "unknown")

    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        llm.get_llm_client()


def test_provider_sdks_are_lazy_imports(monkeypatch):
    real_import = __import__

    def fail_on_provider(name, *args, **kwargs):
        if name in {"anthropic", "openai", "google"} or name.startswith("google.genai"):
            raise AssertionError(f"provider SDK imported eagerly: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fail_on_provider)
    importlib.reload(llm)


def test_anthropic_query_uses_messages_api(monkeypatch):
    create = Mock(
        return_value=types.SimpleNamespace(
            content=[types.SimpleNamespace(text='  {"ok": true}  ')]
        )
    )
    constructor = Mock(
        return_value=types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    )
    monkeypatch.setitem(
        sys.modules, "anthropic", types.SimpleNamespace(Anthropic=constructor)
    )

    client = llm.AnthropicLLM("test-key")
    raw = client.query("claude-test", [{"role": "user", "content": "hi"}], 64)

    assert llm.parse_model_json(raw) == {"ok": True}
    create.assert_called_once_with(
        model="claude-test",
        max_tokens=64,
        messages=[{"role": "user", "content": "hi"}],
    )


def test_openai_query_uses_responses_api(monkeypatch):
    create = Mock(return_value=types.SimpleNamespace(output_text='  {"ok": true}  '))
    constructor = Mock(
        return_value=types.SimpleNamespace(responses=types.SimpleNamespace(create=create))
    )
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=constructor))

    client = llm.OpenAILLM("test-key")
    messages = [{"role": "user", "content": "hi"}]
    raw = client.query("gpt-test", messages, 64)

    assert llm.parse_model_json(raw) == {"ok": True}
    create.assert_called_once_with(
        model="gpt-test", input=messages, max_output_tokens=64
    )


def _fake_google_genai(monkeypatch):
    generate_content = Mock(
        return_value=types.SimpleNamespace(text='  {"ok": true}  ')
    )
    client_instance = types.SimpleNamespace(
        models=types.SimpleNamespace(generate_content=generate_content)
    )
    client_constructor = Mock(return_value=client_instance)
    fake_types = types.SimpleNamespace(
        Part=types.SimpleNamespace(
            from_text=Mock(side_effect=lambda *, text: {"text": text})
        ),
        Content=Mock(side_effect=lambda **kwargs: kwargs),
        GenerateContentConfig=Mock(side_effect=lambda **kwargs: kwargs),
    )
    genai_module = types.ModuleType("google.genai")
    genai_module.Client = client_constructor
    genai_module.types = fake_types
    google_module = types.ModuleType("google")
    google_module.genai = genai_module
    monkeypatch.setitem(sys.modules, "google", google_module)
    monkeypatch.setitem(sys.modules, "google.genai", genai_module)
    return client_constructor, generate_content


def test_gemini_query_converts_text_messages(monkeypatch):
    constructor, generate_content = _fake_google_genai(monkeypatch)

    client = llm.GeminiLLM("test-key")
    raw = client.query(
        "gemini-test",
        [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ],
        64,
    )

    assert llm.parse_model_json(raw) == {"ok": True}
    constructor.assert_called_once_with(api_key="test-key")
    generate_content.assert_called_once_with(
        model="gemini-test",
        contents=[
            {"role": "user", "parts": [{"text": "hello"}]},
            {"role": "model", "parts": [{"text": "hi"}]},
        ],
        config={"max_output_tokens": 64},
    )


def test_gemini_vision_payload_passes_prompt_and_image(monkeypatch):
    _constructor, generate_content = _fake_google_genai(monkeypatch)
    png = base64.b64encode(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    ).decode()
    messages = llm.create_vision_messages("describe", png, provider="gemini")

    client = llm.GeminiLLM("test-key")
    client.query("gemini-test", messages, 32)

    call = generate_content.call_args.kwargs
    assert call["contents"][0] == "describe"
    assert call["contents"][1].size == (1, 1)


def test_vision_message_formats():
    anthropic = llm.create_vision_messages("describe", "abc", provider="anthropic")
    openai = llm.create_vision_messages("describe", "abc", provider="openai")

    assert anthropic[0]["content"][0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "abc",
        },
    }
    assert openai[0]["content"] == [
        {"type": "input_text", "text": "describe"},
        {"type": "input_image", "image_url": "data:image/png;base64,abc"},
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (' {"value": 1} ', {"value": 1}),
        ('```json\n{"value": 2}\n```', {"value": 2}),
        ('```\n[1, 2]\n```', [1, 2]),
    ],
)
def test_parse_model_json(raw, expected):
    assert llm.parse_model_json(raw) == expected


def test_parse_model_json_rejects_non_json():
    with pytest.raises(ValueError):
        llm.parse_model_json("not json")
