import importlib.util
import json
import sys
import types
from pathlib import Path


repo_root = Path(__file__).resolve().parents[1]
sys.path.append(str(repo_root))


def _load_provider_module(genai_stub):
    """Load ``provider_gemini`` with a stubbed ``google.generativeai``."""

    google_module = types.ModuleType("google")
    google_module.generativeai = genai_stub
    sys.modules["google"] = google_module
    sys.modules["google.generativeai"] = genai_stub

    module_path = repo_root / "ai_gateway" / "services" / "provider_gemini.py"
    spec = importlib.util.spec_from_file_location("provider_gemini_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeConfigParameter:
    def __init__(self, values):
        self.values = values

    def sudo(self):
        return self

    def get_param(self, key, default=None):
        return self.values.get(key, default)


def _cleanup_google_modules():
    sys.modules.pop("google.generativeai", None)
    sys.modules.pop("google", None)


def test_models_prefix_removed_for_modern_client():
    captured = {}

    def configure(api_key=None):
        captured["api_key"] = api_key

    class DummyGenerativeModel:
        def __init__(self, name):
            captured["model_name"] = name

        def generate_content(self, parts):
            captured["parts"] = parts
            return types.SimpleNamespace(text="ok", to_dict=lambda: {})

    genai_stub = types.SimpleNamespace(
        configure=configure,
        GenerativeModel=DummyGenerativeModel,
    )

    module = _load_provider_module(genai_stub)
    try:
        env = {
            "ir.config_parameter": FakeConfigParameter(
                {
                    "ai_gateway.gemini_api_key": "KEY",
                    "ai_gateway.gemini_model": "models/gemini-1.5-flash",
                }
            )
        }

        provider = module.GeminiProvider(env)
        result = provider.generate("prompt", system_instruction="sys")

        assert captured["api_key"] == "KEY"
        assert captured["model_name"] == "gemini-1.5-flash"
        assert result["text"] == "ok"
    finally:
        _cleanup_google_modules()


def test_tuned_models_prefix_preserved():
    captured = {}

    class DummyGenerativeModel:
        def __init__(self, name):
            captured["model_name"] = name

        def generate_content(self, parts):  # pragma: no cover - not used
            return types.SimpleNamespace(text="", to_dict=lambda: {})

    genai_stub = types.SimpleNamespace(
        configure=lambda api_key=None: None,
        GenerativeModel=DummyGenerativeModel,
    )

    module = _load_provider_module(genai_stub)
    try:
        env = {
            "ir.config_parameter": FakeConfigParameter(
                {
                    "ai_gateway.gemini_api_key": "KEY",
                    "ai_gateway.gemini_model": "tunedModels/my-model",
                }
            )
        }

        module.GeminiProvider(env)
        assert captured["model_name"] == "tunedModels/my-model"
    finally:
        _cleanup_google_modules()


def test_rest_generate_retries_with_versioned_model():
    attempts = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload
            self.text = json.dumps(payload)

        def json(self):
            return self._payload

    responses = [
        FakeResponse(
            404,
            {
                "error": {
                    "code": 404,
                    "message": "Publisher Model `projects/.../models/gemini-1.5-flash-002` was not found.",
                }
            },
        ),
        FakeResponse(
            404,
            {
                "error": {
                    "code": 404,
                    "message": "Publisher Model `projects/.../models/gemini-1.5-flash-002` was not found.",
                }
            },
        ),
        FakeResponse(
            200,
            {
                "candidates": [
                    {"content": {"parts": [{"text": "ok"}]}}
                ]
            },
        ),
    ]

    def fake_post(url, headers=None, data=None, timeout=None):
        attempts.append(url)
        return responses.pop(0)

    genai_stub = types.SimpleNamespace(configure=lambda api_key=None: None)
    module = _load_provider_module(genai_stub)
    module.requests.post = fake_post

    try:
        env = {
            "ir.config_parameter": FakeConfigParameter(
                {
                    "ai_gateway.gemini_api_key": "KEY",
                    "ai_gateway.gemini_model": "gemini-1.5-flash",
                }
            )
        }

        provider = module.GeminiProvider(env)
        result = provider.generate("prompt")

        assert result["text"] == "ok"
        assert attempts[0].endswith("/models/gemini-1.5-flash:generateContent?key=KEY")
        assert attempts[1].endswith("/models/gemini-1.5-flash-latest:generateContent?key=KEY")
        assert attempts[2].endswith("/models/gemini-1.5-flash-001:generateContent?key=KEY")
        assert provider.model_name == "gemini-1.5-flash-001"
    finally:
        _cleanup_google_modules()
