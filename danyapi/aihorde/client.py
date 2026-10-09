from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

log = logging.getLogger("danyapi.aihorde")

SUBMIT_ENDPOINT = "https://aihorde.net/api/v2/generate/text/async"
STATUS_ENDPOINT = "https://aihorde.net/api/v2/generate/text/status/{task_id}"
MODELS_ENDPOINT = "https://aihorde.net/api/v2/status/models"

ANON_KEY = "0000000000"

MODEL_TARGETS: dict[str, list[str]] = {
    "cydonia-24b": [
        "aphrodite/TheDrummer/Cydonia-24B-v4.3",
        "koboldcpp/Cydonia-24B-v4.3",
        "Cydonia-24B-v4.3",
    ],
    "cydonia": [
        "aphrodite/TheDrummer/Cydonia-24B-v4.3",
        "koboldcpp/Cydonia-24B-v4.3",
    ],
    "gemma-4-heretic": [
        "koboldcpp/Gemma-4-E4B-it-Ultra-Uncensored-Heretic",
        "koboldcpp/gemma-4-31B-it-heretic",
        "koboldcpp/Gemma-4-E4B-Uncensored-HauhauCS-Aggressive-Q4_K_M",
    ],
    "gemma-heretic": [
        "koboldcpp/Gemma-4-E4B-it-Ultra-Uncensored-Heretic",
        "koboldcpp/gemma-4-31B-it-heretic",
    ],
    "skyfall-31b": [
        "aphrodite/TheDrummer/Skyfall-31B-v4.2",
        "koboldcpp/TheDrummer/Skyfall-31B-v4.2",
        "koboldcpp/Skyfall-31B-v4.2",
    ],
    "skyfall": [
        "aphrodite/TheDrummer/Skyfall-31B-v4.2",
        "koboldcpp/TheDrummer/Skyfall-31B-v4.2",
    ],
    "rocinante-12b": [
        "koboldcpp/Rocinante-X-12B",
        "aphrodite/SicariusSicariiStuff/Impish_Bloodmoon_12B",
        "koboldcpp/Angelic_Eclipse-12B",
        "koboldcpp/MN-Violet-Lotus-12B.Q8_0",
        "koboldcpp/ReadyArt/Forgotten-Safeword-22B",
        "aphrodite/TheDrummer/Cydonia-24B-v4.3",
    ],
    "rocinante": [
        "koboldcpp/Rocinante-X-12B",
        "aphrodite/SicariusSicariiStuff/Impish_Bloodmoon_12B",
        "koboldcpp/Angelic_Eclipse-12B",
    ],
    "behemoth-123b": [
        "aphrodite/TheDrummer/Behemoth-X-123B-v2.1",
        "koboldcpp/TheDrummer_Behemoth-128B-v3-Q4_K_M",
    ],
    "behemoth": [
        "aphrodite/TheDrummer/Behemoth-X-123B-v2.1",
    ],
    "stheno-8b": [
        "koboldcpp/L3-8B-Stheno-v3.2",
        "koboldcpp/L3-8B-Stheno-v3.3-32K.Q4_K_M",
        "koboldcpp/L3-8B-Stheno-v3.2-Q5_K_M",
        "koboldcpp/L3-8B-Stheno-v3.2-Q8_0",
    ],
    "magnum-12b": [
        "koboldcpp/mini-magnum-12b-v1.1",
        "aphrodite/TheDrummer/Cydonia-24B-v4.3",
    ],
    "gemma-3-abliterated": [
        "koboldcpp/gemma-3-27b-it-abliterated.q4_k_m",
        "koboldcpp/Gemma-4-E4B-it-Ultra-Uncensored-Heretic",
    ],
    "horde-uncensored": [
        "aphrodite/TheDrummer/Cydonia-24B-v4.3",
        "aphrodite/TheDrummer/Skyfall-31B-v4.2",
        "aphrodite/TheDrummer/Behemoth-X-123B-v2.1",
        "koboldcpp/Cydonia-24B-v4.3",
    ],
}

MODEL_SHORTCUTS: dict[str, str] = {
    "cydonia-24b": "koboldcpp/Cydonia-24B-v4.3",
    "cydonia": "koboldcpp/Cydonia-24B-v4.3",
    "gemma-4-heretic": "koboldcpp/gemma-4-31B-it-heretic",
    "gemma-heretic": "koboldcpp/gemma-4-31B-it-heretic",
    "skyfall-31b": "aphrodite/TheDrummer/Skyfall-31B-v4.2",
    "skyfall": "aphrodite/TheDrummer/Skyfall-31B-v4.2",
    "rocinante-12b": "koboldcpp/Rocinante-X-12B",
    "rocinante": "koboldcpp/Rocinante-X-12B",
    "behemoth-123b": "aphrodite/TheDrummer/Behemoth-X-123B-v2.1",
    "behemoth": "aphrodite/TheDrummer/Behemoth-X-123B-v2.1",
    "magnum-12b": "koboldcpp/mini-magnum-12b-v1.1",
    "gemma-3-abliterated": "koboldcpp/gemma-3-27b-it-abliterated.q4_k_m",
    "horde-uncensored": "koboldcpp/Cydonia-24B-v4.3",
}

MODEL_CATALOG: tuple[dict, ...] = (
    {"id": "cydonia-24b", "name": "Cydonia 24B v4.3", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "cydonia", "name": "Cydonia 24B", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "gemma-4-heretic", "name": "Gemma 4 31B Heretic", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "gemma-heretic", "name": "Gemma Heretic", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "skyfall-31b", "name": "Skyfall 31B v4.2", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "skyfall", "name": "Skyfall", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "rocinante-12b", "name": "Rocinante X 12B", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "rocinante", "name": "Rocinante", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "behemoth-123b", "name": "Behemoth X 123B v2.1", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "behemoth", "name": "Behemoth", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "stheno-8b", "name": "Stheno 8B v3.2", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "magnum-12b", "name": "Mini Magnum 12B v1.1", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "gemma-3-abliterated", "name": "Gemma 3 27B Abliterated", "owned_by": "aihorde", "model_type": "chat"},
    {"id": "horde-uncensored", "name": "Horde Uncensored", "owned_by": "aihorde", "model_type": "chat"},
)

DEFAULT_MODEL = "cydonia-24b"

POLL_INTERVAL = 1.5
POLL_ATTEMPTS = 60

STOP_SEQUENCES = [
    "### User:", "### Assistant:", "### System:", "\n###",
    "<|im_end|>", "<|end_of_text|>", "</s>", "\nUser:", "\nAssistant:",
]

CLEAN_PREFIXES = ("### Assistant:", "### Assistant", "Assistant:")
CLEAN_STOPS = (
    "### User:", "### Assistant:", "### System:", "###",
    "<|im_end|>", "<|end_of_text|>", "</s>",
    "\n**User:**", "**User:**", "\nUser:", "\nHuman:", "\nAssistant:",
)


def catalog_models() -> tuple[dict, ...]:
    return MODEL_CATALOG


def resolve_model_targets(model: str) -> list[str]:
    lowered = model.lower()
    targets = MODEL_TARGETS.get(lowered)
    if targets:
        return targets
    shortcut = MODEL_SHORTCUTS.get(lowered, model)
    return [shortcut]


class AIHordeError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"AI Horde error {code}: {message}")
        self.code = code
        self.message = message


def _format_prompt(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if isinstance(content, list):
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text")
        content = str(content or "").strip()
        reasoning = msg.get("reasoning_content") or msg.get("thinking") or ""
        if isinstance(reasoning, list):
            reasoning = "".join(p.get("text", "") for p in reasoning if isinstance(p, dict))
        reasoning = str(reasoning or "").strip()
        if not content and not reasoning:
            continue
        if role == "system":
            parts.append(f"### System:\n{content}\n")
        elif role == "user":
            parts.append(f"### User:\n{content}\n")
        elif role == "assistant":
            if reasoning:
                parts.append(f"### Assistant reasoning:\n{reasoning}\n")
            parts.append(f"### Assistant:\n{content}\n")
    parts.append("### Assistant:\n")
    return "\n".join(parts)


def _clean_text(text: str) -> str:
    text = text.strip()
    for prefix in CLEAN_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    for stop in CLEAN_STOPS:
        if stop in text:
            text = text.split(stop)[0].strip()
    return text


class AIHordeClient:
    def __init__(
        self,
        api_key: str = ANON_KEY,
        timeout: float = 90.0,
    ) -> None:
        self.api_key = api_key or ANON_KEY
        self.timeout = float(timeout)
        self.http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, read=max(float(timeout) * 5, 300.0)),
            limits=httpx.Limits(max_keepalive_connections=20, keepalive_expiry=30.0),
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def check_auth(self) -> bool:
        try:
            resp = await self.http.get(
                MODELS_ENDPOINT,
                headers={"apikey": self.api_key},
                timeout=httpx.Timeout(15.0, connect=10.0),
            )
            return resp.status_code == 200
        except (httpx.HTTPError, OSError, RuntimeError):
            return False

    async def fetch_models(self) -> list[dict]:
        return [dict(entry) for entry in catalog_models()]

    async def generate(
        self,
        prompt: str,
        model: str,
        *,
        max_tokens: int = 500,
        max_context_length: int = 3072,
        temperature: float = 0.7,
        stop_sequences: list[str] | None = None,
    ) -> str:
        models = resolve_model_targets(model)
        safe_max_tokens = min(int(max_tokens), 500)
        safe_context = min(int(max_context_length), 4096)

        stops = list(STOP_SEQUENCES)
        if stop_sequences:
            stops.extend(s for s in stop_sequences if isinstance(s, str))

        payload: dict[str, Any] = {
            "prompt": prompt,
            "params": {
                "max_context_length": safe_context,
                "max_length": safe_max_tokens,
                "temperature": float(temperature),
                "stop_sequence": stops,
            },
            "models": models,
        }

        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        timeout_cfg = httpx.Timeout(self.timeout, connect=10.0)

        submit_resp = await self.http.post(
            SUBMIT_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=timeout_cfg,
        )
        if submit_resp.status_code not in (200, 202):
            raise AIHordeError(
                submit_resp.status_code,
                submit_resp.text[:200],
            )

        task_data = submit_resp.json()
        task_id = task_data.get("id")
        if not task_id:
            raise AIHordeError(502, f"no task id returned: {task_data}")

        status_url = STATUS_ENDPOINT.format(task_id=task_id)
        last_error: str | None = None

        for _ in range(POLL_ATTEMPTS):
            await asyncio.sleep(POLL_INTERVAL)
            try:
                chk_resp = await self.http.get(status_url, headers={"apikey": self.api_key}, timeout=timeout_cfg)
            except (httpx.HTTPError, OSError, RuntimeError) as exc:
                last_error = f"status request failed: {exc}"
                log.debug("horde polling retry: %s", exc)
                continue
            if chk_resp.status_code in (401, 403):
                raise AIHordeError(chk_resp.status_code, chk_resp.text[:200])
            if chk_resp.status_code != 200:
                last_error = f"status HTTP {chk_resp.status_code}: {chk_resp.text[:200]}"
                continue
            try:
                chk = chk_resp.json()
            except ValueError as exc:
                last_error = f"status decode failed: {exc}"
                continue
            if chk.get("faulted"):
                raise AIHordeError(502, "task faulted on worker node")
            if chk.get("done"):
                generations = chk.get("generations", [])
                if generations:
                    return generations[0].get("text", "")
                break

        raise AIHordeError(504, last_error or f"task {task_id} timed out or returned no content")
