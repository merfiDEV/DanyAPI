import os

import pytest

os.environ["BYOK"] = "0"
for _key in (
    "DEEPSEEK_TOKENS",
    "QWEN_TOKENS",
    "GIGACHAT_KEYS",
    "GIGACHAT_SCOPE",
    "DANYAPI_GIGACHAT_CA_FILE",
    "OPENCODE_KEYS",
    "ALICE_ACCOUNTS",
    "DUCKAI_ACCOUNTS",
    "MISTRAL_LOGINS",
    "AISTUDIO_LOGINS",
    "AIHORDE_API_KEYS",
    "DANYAPI_DISABLED_PROVIDERS",
):
    os.environ[_key] = ""


@pytest.fixture(autouse=True)
def _admin_token(monkeypatch):
    from danyapi.config import settings

    monkeypatch.setattr(settings, "admin_token", "test-admin-token", raising=False)
