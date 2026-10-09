from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi import HTTPException

from ..accounts import account_lock
from ..api.retry import MAX_RETRIES, RETRYABLE_HTTP_STATUSES, _retry_delay
from ..api.shaping import _apply_limits
from ..api.sse import _sse, _stream_error_sse
from ..config import settings
from ..sseutil import StreamStopFilter, split_stop
from ..tokens import StreamBudget, estimate_tokens, trim_to_tokens
from ..tools import DsmlFilter, strip_dsml
from ..usage import record_usage_dict
from .client import DEFAULT_MODEL, AIHordeClient, AIHordeError, _clean_text, _format_prompt

log = logging.getLogger("danyapi.aihorde.api")

RETRY_JITTER = 0.5

DONE_LINE = "data: [DONE]\n\n"

PROVIDER = "aihorde"


def _status_for(error: AIHordeError) -> int:
    code = error.code if isinstance(error.code, int) else 502
    if code in (401, 403):
        return 401
    if code == 429:
        return 429
    if code in RETRYABLE_HTTP_STATUSES:
        return 502
    if 400 <= code < 500:
        return 400
    return 502


def _detail_for(error: AIHordeError) -> str:
    return f"aihorde error: {error.message or error.code}"


def _http_error(error: AIHordeError) -> HTTPException:
    return HTTPException(_status_for(error), _detail_for(error))


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") in ("text", "input_text"):
                text = item.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _render_messages(messages: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for message in messages or []:
        role = getattr(message, "role", None)
        content = getattr(message, "content", None)
        text = _text_of(content)
        entry: dict[str, Any] = {"role": role or "user", "content": text}
        reasoning = getattr(message, "reasoning_content", None) or getattr(message, "thinking", None)
        if reasoning:
            entry["reasoning_content"] = _text_of(reasoning)
        out.append(entry)
    return out


def _usage_for(prompt: str, content: str) -> dict:
    prompt_tokens = estimate_tokens(prompt)
    completion_tokens = estimate_tokens(content)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": 0},
        "completion_tokens_details": {"reasoning_tokens": 0},
    }


class _Retry(Exception):
    pass


class _HordeText:
    __slots__ = ("text",)

    def __init__(self, text: str) -> None:
        self.text = text


async def _stream_events(
    account: Any,
    prompt: str,
    model: str,
    max_tokens: int,
    max_context_length: int,
    temperature: float,
    stop_sequences: list[str],
    prelude: tuple[str, ...] = (),
) -> AsyncIterator[Any]:
    attempt = 0
    started = False
    while True:
        async with contextlib.AsyncExitStack() as stack:
            await stack.enter_async_context(account_lock(account.sem, settings.acquire_timeout))
            if not started:
                started = True
                for line in prelude:
                    yield line
            try:
                async for event in _open_stream(
                    account,
                    prompt,
                    model,
                    max_tokens,
                    max_context_length,
                    temperature,
                    stop_sequences,
                    attempt,
                ):
                    yield event
                return
            except _Retry:
                pass
        await _sleep_backoff(attempt)
        attempt += 1


async def _open_stream(
    account: Any,
    prompt: str,
    model: str,
    max_tokens: int,
    max_context_length: int,
    temperature: float,
    stop_sequences: list[str],
    attempt: int,
) -> AsyncIterator[_HordeText]:
    client: AIHordeClient = account.client
    try:
        text = await client.generate(
            prompt,
            model,
            max_tokens=max_tokens,
            max_context_length=max_context_length,
            temperature=temperature,
            stop_sequences=stop_sequences,
        )
    except httpx.HTTPError as exc:
        status = getattr(getattr(exc, "response", None), "status_code", 0) or 0
        if status in RETRYABLE_HTTP_STATUSES and attempt < MAX_RETRIES:
            raise _Retry() from exc
        raise HTTPException(502, f"aihorde transport error: {exc}") from exc
    except AIHordeError as exc:
        if exc.code in RETRYABLE_HTTP_STATUSES and attempt < MAX_RETRIES:
            raise _Retry() from exc
        raise _http_error(exc) from exc
    yield _HordeText(text)


async def _sleep_backoff(attempt: int) -> None:
    base = _retry_delay(attempt + 1)
    if base <= 0:
        return
    await asyncio.sleep(base * (1.0 - RETRY_JITTER + random.random() * RETRY_JITTER))


async def collect_non_stream(
    account,
    messages,
    model: str = DEFAULT_MODEL,
    tools=None,
    tool_choice=None,
    functions=None,
    stop: Any = None,
    max_tokens: int | None = None,
    user: str | None = None,
    session_id: str | None = None,
) -> dict:
    rendered = _render_messages(messages)
    prompt = _format_prompt(rendered)
    stop_markers = split_stop(stop)
    stop_sequences = list(stop_markers) if stop_markers else []

    raw_max = max_tokens or 500
    content = ""
    finish = "stop"

    async for event in _stream_events(
        account,
        prompt,
        model,
        raw_max,
        3072,
        0.7,
        stop_sequences,
    ):
        content = event.text

    content = _clean_text(content)
    text, limit_finish = _apply_limits(strip_dsml(content), max_tokens, stop)
    if limit_finish == "length":
        finish = "length"
    message: dict[str, Any] = {"role": "assistant", "content": text}
    usage = _usage_for(prompt, text)
    record_usage_dict(PROVIDER, model, usage, user=user, session_id=session_id)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "system_fingerprint": "fp_aihorde",
        "choices": [{"index": 0, "message": message, "finish_reason": finish, "logprobs": None}],
        "usage": usage,
        "session_id": session_id,
    }


def _chunk(chunk_id: str, created: int, model: str, delta: dict, finish: str | None = None, usage: dict | None = None) -> str:
    payload: dict[str, Any] = {
        "id": chunk_id,
        "object": "chat.completion.chunk",
        "created": created,
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage is not None:
        payload["usage"] = usage
    return _sse(payload)


async def stream_openai(
    account,
    messages,
    model: str = DEFAULT_MODEL,
    tools=None,
    tool_choice=None,
    functions=None,
    stop: Any = None,
    max_tokens: int | None = None,
    include_usage: bool = False,
    user: str | None = None,
    session_id: str | None = None,
) -> AsyncIterator[str]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex}"
    created = int(time.time())
    rendered = _render_messages(messages)
    prompt = _format_prompt(rendered)
    stop_markers = split_stop(stop)
    stop_sequences = list(stop_markers) if stop_markers else []
    raw_max = max_tokens or 500

    content: list[str] = []
    emitted = False
    finish = "stop"
    stop_filter = StreamStopFilter(stop_markers) if stop_markers else None
    budget = StreamBudget(max_tokens, trim_to_tokens)
    stop_hit = False
    content_filter = DsmlFilter()

    try:
        async for item in _stream_events(
            account,
            prompt,
            model,
            raw_max,
            3072,
            0.7,
            stop_sequences,
            prelude=(_chunk(chunk_id, created, model, {"role": "assistant"}),),
        ):
            if isinstance(item, str):
                yield item
                continue
            raw_text = _clean_text(item.text)
            raw_text = content_filter.feed(raw_text)
            if stop_filter is not None and not stop_hit:
                raw_text, hit = stop_filter.feed(raw_text)
                stop_hit = stop_hit or hit
            elif stop_hit:
                raw_text = ""
            raw_text = budget.feed(raw_text)
            if raw_text:
                words = raw_text.split(" ")
                for i, word in enumerate(words):
                    piece = word + (" " if i < len(words) - 1 else "")
                    if piece:
                        content.append(piece)
                        emitted = True
                        yield _chunk(chunk_id, created, model, {"content": piece})
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        record_usage_dict(PROVIDER, model, _usage_for(prompt, "".join(content)), user=user, session_id=session_id)
        for line in _stream_error_sse(chunk_id, created, model, detail, session_id):
            yield line
        return

    tail = content_filter.flush()
    if stop_filter is not None and not stop_hit:
        tail, hit = stop_filter.feed(tail)
        stop_hit = stop_hit or hit
        if stop_hit:
            tail = ""
        else:
            tail += stop_filter.flush()
    else:
        tail = "" if stop_hit else tail
    tail = budget.feed(tail)
    if tail:
        words = tail.split(" ")
        for i, word in enumerate(words):
            piece = word + (" " if i < len(words) - 1 else "")
            if piece:
                content.append(piece)
                emitted = True
                yield _chunk(chunk_id, created, model, {"content": piece})
    if budget.done:
        finish = "length"
    if not emitted:
        yield _chunk(chunk_id, created, model, {"content": ""})
    yield _chunk(chunk_id, created, model, {}, finish)
    usage = _usage_for(prompt, "".join(content))
    record_usage_dict(PROVIDER, model, usage, user=user, session_id=session_id)
    if include_usage:
        yield _chunk(chunk_id, created, model, {}, None, usage=usage)
    yield DONE_LINE
