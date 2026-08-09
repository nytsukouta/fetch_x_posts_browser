"""Azure OpenAI API と .env 読込の共通ヘルパー。

`extract_events_github_models.py`, `build_event_cumulative.py`,
`smoke_test_github_models.py` などから利用される。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import quote, urlparse


DEFAULT_MODEL = "gpt-5-4-nano"
DEFAULT_API_VERSION = "2024-10-21"

# X の画像 CDN だけを許可（SSRF 防止）。pbs.twimg.com 以外も twimg.com 配下なら許可。
_ALLOWED_IMAGE_HOST_SUFFIXES = ("twimg.com",)


class AzureOpenAIContentPolicyViolation(RuntimeError):
    """Azure OpenAI が content_policy_violation を返した場合に送出。"""


def load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def get_azure_openai_api_key() -> str:
    return os.getenv("AZURE_OPENAI_API_KEY", "").strip()


def build_chat_completions_url(endpoint: str, deployment: str, api_version: str) -> str:
    base_url = endpoint.strip().rstrip("/")
    if not base_url:
        raise ValueError("AZURE_OPENAI_ENDPOINT が設定されていません。")
    if not deployment.strip():
        raise ValueError("AZURE_OPENAI_DEPLOYMENT が設定されていません。")
    return (
        f"{base_url}/openai/deployments/{quote(deployment.strip(), safe='')}/chat/completions"
        f"?api-version={quote(api_version.strip(), safe='')}"
    )


def is_safe_image_url(url: str) -> bool:
    """SSRF 防止: https かつ twimg.com 配下のホストのみ True。"""
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme != "https":
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    return any(host == suffix or host.endswith("." + suffix) for suffix in _ALLOWED_IMAGE_HOST_SUFFIXES)


def filter_safe_image_urls(urls: list[str]) -> list[str]:
    safe: list[str] = []
    for url in urls:
        if is_safe_image_url(url):
            safe.append(url)
        elif url.strip():
            print(f"skipping unsafe image url: {url}", file=sys.stderr)
    return safe


def call_chat_completion(
    *,
    token: str,
    api_version: str,
    model: str,
    messages: list[dict[str, Any]],
    response_format: dict[str, Any] | None = None,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    timeout: float = 60.0,
    max_attempts: int = 5,
    retry_label: str = "",
) -> dict[str, Any]:
    """Azure OpenAI chat completions を呼び出す共通実装。

    - 429/500/502/503/504 は exponential backoff で最大 max_attempts 回まで再試行
    - Retry-After ヘッダを尊重
    - HTTP 400 で content_policy_violation を含む場合は AzureOpenAIContentPolicyViolation
    """
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    inference_url = build_chat_completions_url(endpoint, model, api_version)
    payload: dict[str, Any] = {"messages": messages, "temperature": temperature}
    if response_format is not None:
        payload["response_format"] = response_format
    if max_tokens is not None:
        token_limit_field = "max_completion_tokens" if model.lower().startswith("gpt-5") else "max_tokens"
        payload[token_limit_field] = max_tokens

    label = f" [{retry_label}]" if retry_label else ""
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        api_request = request.Request(
            inference_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "api-key": token,
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(api_request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code == 400 and "content_policy_violation" in details:
                raise AzureOpenAIContentPolicyViolation(details) from exc
            if exc.code not in {429, 500, 502, 503, 504} or attempt == max_attempts - 1:
                raise RuntimeError(f"Azure OpenAI API error {exc.code}: {details}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            wait_seconds = float(retry_after) if retry_after else min(30, 2 * (attempt + 1))
            print(f"retrying{label} after API error {exc.code}: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc
        except error.URLError as exc:
            # urlopen の timeout は URLError(reason=socket.timeout) で来る
            if attempt == max_attempts - 1:
                raise RuntimeError(f"Azure OpenAI API へ接続できません: {exc}") from exc
            wait_seconds = min(30, 2 * (attempt + 1))
            reason = getattr(exc, "reason", exc)
            print(f"retrying{label} after connection error ({reason}): wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc
        except TimeoutError as exc:
            if attempt == max_attempts - 1:
                raise RuntimeError(f"Azure OpenAI API の応答待ちがタイムアウトしました: {exc}") from exc
            wait_seconds = min(30, 2 * (attempt + 1))
            print(f"retrying{label} after read timeout: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc

    raise RuntimeError(f"Azure OpenAI API の呼び出しに失敗しました: {last_error}")
