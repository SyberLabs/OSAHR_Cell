"""Thin Qwen proposal adapter. It has no admission authority."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlparse

QWEN_MODEL = "Qwen/Qwen3-Coder-Next"


@dataclass(frozen=True)
class ProviderReply:
    value: object
    model: str
    usage: dict
    elapsed_ms: int
    request_id: str | None
    revision: str | None = None


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _revision(result: dict) -> str | None:
    value = result.get("system_fingerprint") or result.get("model_revision")
    return value if isinstance(value, str) and value else None


def _post_json(url: str, payload: dict, token: str, timeout: float,
               max_input_bytes: int) -> tuple[dict, str | None, int]:
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in
                                          {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("provider endpoint must be HTTPS or loopback")
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    # UTF-8 bytes are a conservative upper bound for tokenized text.
    if len(body) > max_input_bytes:
        raise ValueError("provider_input_cap_exceeded")
    call = request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    started = time.monotonic()
    try:
        with request.build_opener(_NoRedirect()).open(call, timeout=timeout) as response:
            # Provider responses are untrusted and bounded before parsing.
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("provider response too large")
            request_id = response.headers.get("x-request-id")
    except error.HTTPError as exc:
        raise RuntimeError(f"provider_http_{exc.code}") from None
    except (error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"provider_transport_{type(exc).__name__}") from None
    try:
        result = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("provider response is not JSON") from None
    if not isinstance(result, dict):
        raise ValueError("provider response is not an object")
    return result, request_id, int((time.monotonic() - started) * 1000)


class QwenBuilder:
    def __init__(self, *, endpoint: str = "https://router.huggingface.co/v1/chat/completions",
                 token_env: str = "HF_TOKEN", timeout: float = 45.0,
                 max_input_bytes: int = 100_000) -> None:
        self.endpoint, self.token_env, self.timeout = endpoint, token_env, timeout
        self.max_input_bytes = max_input_bytes

    def propose(self, *, component: str, source: str, contract: str,
                diagnostic: str, max_tokens: int) -> ProviderReply:
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError("qwen_credential_unavailable")
        state = {
            "component": component, "current_source": source[:24_000],
            "public_contract": contract[:12_000],
            "observed_public_diagnostic": diagnostic[:8_000],
            "allowed_output": {"module": "complete service.py", "tests": "public candidate tests"},
            "module_language": ("Pure functions only; import json is the only module import. "
                                "No top-level effects, decorators, reflection, process control, "
                                "I/O, print, or calls outside basic builtins, json.loads/dumps, "
                                "and dict/list/string methods. Raise ValueError or TypeError."),
        }
        payload = {"model": QWEN_MODEL, "stream": False, "max_tokens": max_tokens,
                   "messages": [
                       {"role": "system", "content": "Return one JSON object with only module and tests strings. Propose code; do not claim acceptance or request tools."},
                       {"role": "user", "content": json.dumps(state, sort_keys=True)},
                   ]}
        result, request_id, elapsed = _post_json(
            self.endpoint, payload, token, self.timeout, self.max_input_bytes)
        if result.get("model") != QWEN_MODEL:
            raise ValueError("qwen_model_identity_mismatch")
        try:
            content = result["choices"][0]["message"]["content"]
            proposal = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ValueError("qwen_invalid_proposal") from None
        if (not isinstance(proposal, dict) or set(proposal) != {"module", "tests"}
                or any(not isinstance(proposal[key], str) or not proposal[key].strip()
                       or len(proposal[key]) > 50_000 for key in ("module", "tests"))):
            raise ValueError("qwen_invalid_proposal")
        usage = result.get("usage")
        return ProviderReply(proposal, QWEN_MODEL, usage if isinstance(usage, dict) else {},
                             elapsed, request_id or result.get("id"),
                             revision=_revision(result))
