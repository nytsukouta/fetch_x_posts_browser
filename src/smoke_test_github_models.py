from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from github_models_client import (
    DEFAULT_API_VERSION,
    call_chat_completion,
    get_github_models_token,
    load_dotenv,
)


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_MODEL = "openai/gpt-5"
DEFAULT_SYSTEM_PROMPT = "You are a concise assistant. Reply in Japanese unless asked otherwise."
DEFAULT_USER_PROMPT = "これは GitHub Models の疎通確認です。model_id を文中に含めて一言だけ返してください。"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GitHub Models の任意モデルを試す簡易スモークテスト")
    parser.add_argument("--model", default=os.getenv("GITHUB_MODELS_MODEL", DEFAULT_MODEL), help="試したい GitHub Models の model ID")
    parser.add_argument("--prompt", default=DEFAULT_USER_PROMPT, help="user メッセージとして送る本文")
    parser.add_argument("--system-prompt", default=DEFAULT_SYSTEM_PROMPT, help="system メッセージ")
    parser.add_argument("--api-version", default=os.getenv("GITHUB_MODELS_API_VERSION", DEFAULT_API_VERSION), help="X-GitHub-Api-Version")
    parser.add_argument("--temperature", type=float, default=0.0, help="temperature")
    parser.add_argument("--max-tokens", type=int, default=300, help="max_tokens")
    parser.add_argument("--raw-json", action="store_true", help="API 応答 JSON をそのまま表示する")
    return parser.parse_args()


def extract_text_content(response_payload: dict[str, Any]) -> str:
    content = response_payload.get("choices", [{}])[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
        return "".join(text_parts).strip()
    if isinstance(content, str):
        return content.strip()
    return json.dumps(content, ensure_ascii=False)


def main() -> int:
    args = parse_args()
    load_dotenv(DEFAULT_ENV_FILE)
    token = get_github_models_token()
    if not token:
        print("GH_MODELS_TOKEN または GITHUB_TOKEN が見つかりません。.env または環境変数を確認してください。", file=sys.stderr)
        return 1

    response_payload = call_chat_completion(
        token=token,
        api_version=args.api_version,
        model=args.model,
        messages=[
            {"role": "system", "content": args.system_prompt},
            {"role": "user", "content": args.prompt},
        ],
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        retry_label="smoke",
    )

    print(f"model: {args.model}")
    if args.raw_json:
        print(json.dumps(response_payload, ensure_ascii=False, indent=2))
    else:
        print(extract_text_content(response_payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
