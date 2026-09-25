"""Thin, replaceable live adapters. Neither provider has admission authority."""
from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from urllib import error, request
from urllib.parse import urlparse

QWEN_MODEL = "Qwen/Qwen3-Coder-Next"
JEV_MODEL = "jev-latest"


@dataclass(frozen=True)
class ProviderReply:
    value: object
    model: str
    usage: dict
    elapsed_ms: int
    request_id: str | None
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
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
                diagnostic: str, prior_attempts: list[dict], max_tokens: int) -> ProviderReply:
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError("qwen_credential_unavailable")
        state = {
            "component": component, "current_source": source[:24_000],
            "public_contract": contract[:12_000],
            "observed_public_diagnostic": diagnostic[:8_000],
            "prior_attempts": prior_attempts[-3:],
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

    def choose(self, *, state: dict, candidates: list[dict]) -> ProviderReply:
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError("qwen_credential_unavailable")
        ids = {item["id"] for item in candidates}
        payload = {"model": QWEN_MODEL, "stream": False, "max_tokens": 64,
                   "messages": [
                       {"role": "system", "content": "Choose one supplied legal action. Return only a JSON object with key choice."},
                       {"role": "user", "content": json.dumps({"state": state, "candidates": candidates}, sort_keys=True)},
                   ]}
        result, request_id, elapsed = _post_json(
            self.endpoint, payload, token, self.timeout, self.max_input_bytes)
        if result.get("model") != QWEN_MODEL:
            raise ValueError("qwen_model_identity_mismatch")
        try:
            answer = json.loads(result["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ValueError("qwen_invalid_choice") from None
        if not isinstance(answer, dict) or set(answer) != {"choice"} or answer["choice"] not in ids:
            raise ValueError("qwen_invalid_choice")
        usage = result.get("usage")
        return ProviderReply(answer["choice"], QWEN_MODEL,
                             usage if isinstance(usage, dict) else {}, elapsed,
                             request_id or result.get("id"),
                             revision=_revision(result))


class JevChoice:
    def __init__(self, *, endpoint: str = "https://api.typesafe.ai/v1/systemone",
                 token_env: str = "TYPESAFE_API_KEY", timeout: float = 15.0,
                 min_confidence: float = 0.65,
                 max_input_bytes: int = 100_000) -> None:
        if not 0 <= min_confidence <= 1:
            raise ValueError("invalid confidence threshold")
        self.endpoint, self.token_env = endpoint, token_env
        self.timeout, self.min_confidence = timeout, min_confidence
        self.max_input_bytes = max_input_bytes

    def choose(self, *, state: dict, candidates: list[dict]) -> ProviderReply:
        if not 1 <= len(candidates) <= 255:
            raise ValueError("choice requires 1..255 candidates")
        token = os.environ.get(self.token_env)
        if not token:
            raise RuntimeError("jev_credential_unavailable")
        criteria = {candidate["id"]: candidate["description"] for candidate in candidates}
        payload = {"state": state, "model": JEV_MODEL,
                   "questions": {"next_action": {
                       "type": "choice",
                       "instructions": "Choose the most useful legal next action given observed evidence and resource limits. Hypotheses are not observations.",
                       "criteria": criteria,
                   }}}
        result, request_id, elapsed = _post_json(
            self.endpoint, payload, token, self.timeout, self.max_input_bytes)
        answer = result.get("answers", {}).get("next_action", {})
        choice, confidence, probabilities = (answer.get("choice"), answer.get("confidence"),
                                             answer.get("probabilities"))
        if (answer.get("type") != "choice" or choice not in criteria
                or not isinstance(confidence, (float, int)) or isinstance(confidence, bool)
                or not math.isfinite(confidence) or not 0 <= confidence <= 1
                or not isinstance(probabilities, dict) or set(probabilities) != set(criteria)
                or any(not isinstance(v, (float, int)) or isinstance(v, bool)
                       or not math.isfinite(v) or not 0 <= v <= 1
                       for v in probabilities.values())
                or abs(sum(probabilities.values()) - 1) > 0.02):
            raise ValueError("jev_invalid_choice")
        usage = result.get("usage")
        return ProviderReply(choice, str(result.get("model") or ""),
                             usage if isinstance(usage, dict) else {}, elapsed,
                             request_id or result.get("request_id"), float(confidence),
                             {key: float(value) for key, value in probabilities.items()},
                             _revision(result))
