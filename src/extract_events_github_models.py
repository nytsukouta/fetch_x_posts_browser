from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
from typing import Any
from urllib import error, request


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "output" / "x_browser_search_20260508_124323.csv"
DEFAULT_OUTPUT_JSONL = ROOT_DIR / "data" / "output" / "structured_events.jsonl"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "structured_events.csv"
DEFAULT_FILTERED_JSONL = ROOT_DIR / "data" / "output" / "structured_events_filtered.jsonl"
DEFAULT_FILTERED_CSV = ROOT_DIR / "data" / "output" / "structured_events_filtered.csv"
DEFAULT_MODEL = "openai/gpt-4.1-mini"
DEFAULT_API_VERSION = "2026-03-10"
INFERENCE_URL = "https://models.github.ai/inference/chat/completions"

CITY_ALIASES = {
    "金沢": "石川県金沢市",
    "金沢市": "石川県金沢市",
    "七尾": "石川県七尾市",
    "七尾市": "石川県七尾市",
    "白山": "石川県白山市",
    "白山市": "石川県白山市",
    "小松": "石川県小松市",
    "小松市": "石川県小松市",
    "加賀": "石川県加賀市",
    "加賀市": "石川県加賀市",
    "能登": "石川県能登地方",
    "石川": "石川県",
    "石川県": "石川県",
}

VENUE_ALIASES = {
    "金沢おぐら座": "金沢おぐら座",
    "能登演劇堂": "能登演劇堂",
    "金沢市民芸術村pit2ドラマ工房": "金沢市民芸術村PIT2ドラマ工房",
    "ダブル金沢": "ダブル金沢",
    "az": "AZ",
}

NOISE_TEXT_PATTERNS = [
    "商願",
    "商標",
    "出願",
    "日記",
    "本書",
    "論説",
    "委員会",
    "紹介文",
]

REPORT_TEXT_PATTERNS = [
    "楽しかった",
    "反響を呼んでいます",
    "チャンネルで公開",
    "記事",
    "紹介",
    "感想",
    "書籍",
]

THEATER_TEXT_PATTERNS = [
    "公演",
    "上演",
    "劇団",
    "演劇",
    "舞台",
    "朗読劇",
    "ワークショップ",
    "オーディション",
    "当日券",
    "チケット",
    "出演",
]


SYSTEM_PROMPT = """あなたは日本語のX投稿から演劇イベント情報を構造化抽出するアシスタントです。
本文に書かれている情報だけを使ってください。推測しないでください。
不明な項目は null にしてください。
出力は必ずJSONオブジェクトのみで返してください。説明文は不要です。

この処理の目的は演劇関連情報だけを残すことです。
映画、上映会、音楽ライブ、コンサート、DJイベント、アイドルイベント、展示、トークイベント、配信番組、一般ニュースは原則として演劇関連ではありません。
ただし、舞台挨拶ではなく実際の演劇公演、朗読劇、演劇ワークショップ、劇団の出演募集、演劇フェスティバルは演劇関連として扱ってください。

抽出項目:
- event_name: 公演名や企画名
- normalized_event_name: 同一公演の表記揺れ統合用の名称。副題、装飾記号、告知用の余分な説明はなるべく外し、同じ公演なら同じ名前に寄せる
- organization: 劇団名、主催名、出演団体名
- venue_name: 会場名
- location: 地域名、住所、都市名
- start_date: YYYY-MM-DD 形式。年が明示されない場合は投稿日時を基準に補ってよい
- end_date: YYYY-MM-DD 形式。単日なら start_date と同じか null
- start_time: HH:MM 24時間表記。不明なら null
- category: 公演、募集、ワークショップ、朗読劇、その他 のいずれか
- content_type: 演劇、映画、音楽ライブ、トーク、展示、配信、その他 のいずれか
- is_theater_related: 演劇関連なら true、それ以外は false
- is_recruitment: true か false
- confidence: 0 から 1 の数値
- exclusion_reason: 演劇関連ではない場合の短い理由。演劇関連なら null
- reasoning: 1文で簡潔に判断根拠を書く
"""


def get_github_models_token() -> str:
    return os.getenv("GH_MODELS_TOKEN", "").strip() or os.getenv("GITHUB_TOKEN", "").strip()


def load_dotenv(env_path: Path) -> None:
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract theater event fields from collected X posts using GitHub Models")
    parser.add_argument("--input-csv", default=str(DEFAULT_INPUT_CSV), help="収集済みCSVのパス")
    parser.add_argument("--output-jsonl", default=str(DEFAULT_OUTPUT_JSONL), help="構造化結果JSONLの保存先")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="構造化結果CSVの保存先")
    parser.add_argument("--filtered-output-jsonl", default=str(DEFAULT_FILTERED_JSONL), help="ノイズ除去後JSONLの保存先")
    parser.add_argument("--filtered-output-csv", default=str(DEFAULT_FILTERED_CSV), help="ノイズ除去後CSVの保存先")
    parser.add_argument("--limit", type=int, default=None, help="処理件数の上限")
    parser.add_argument("--model", default=os.getenv("GITHUB_MODELS_MODEL", DEFAULT_MODEL), help="GitHub Models のモデルID")
    parser.add_argument("--workers", type=int, default=2, help="GitHub Models 抽出の並列数")
    return parser.parse_args()


def load_rows(input_csv: Path, limit: int | None) -> list[dict[str, str]]:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if limit is not None:
        return rows[:limit]
    return rows


def build_user_prompt(row: dict[str, str]) -> str:
    return json.dumps(
        {
            "query_label": row.get("query_label"),
            "tweet_url": row.get("tweet_url"),
            "created_at": row.get("created_at"),
            "author_name": row.get("author_name"),
            "author_username": row.get("author_username"),
            "text": row.get("text"),
        },
        ensure_ascii=False,
        indent=2,
    )


def call_github_models(token: str, api_version: str, model: str, prompt: str) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }

    last_error: Exception | None = None
    for attempt in range(5):
        api_request = request.Request(
            INFERENCE_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": api_version,
            },
            method="POST",
        )

        try:
            with request.urlopen(api_request, timeout=60) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            if exc.code not in {429, 500, 502, 503, 504} or attempt == 4:
                raise RuntimeError(f"GitHub Models API error {exc.code}: {details}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            wait_seconds = float(retry_after) if retry_after else min(30, 2 * (attempt + 1))
            print(f"retrying after API error {exc.code}: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc
        except error.URLError as exc:
            if attempt == 4:
                raise RuntimeError(f"GitHub Models API へ接続できません: {exc}") from exc
            wait_seconds = min(30, 2 * (attempt + 1))
            print(f"retrying after connection error: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc
        except TimeoutError as exc:
            if attempt == 4:
                raise RuntimeError(f"GitHub Models API の応答待ちがタイムアウトしました: {exc}") from exc
            wait_seconds = min(30, 2 * (attempt + 1))
            print(f"retrying after read timeout: wait {wait_seconds:.0f}s", file=sys.stderr)
            time.sleep(wait_seconds)
            last_error = exc

    raise RuntimeError(f"GitHub Models API の呼び出しに失敗しました: {last_error}")


def extract_json_content(response_payload: dict[str, Any]) -> dict[str, Any]:
    content = response_payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        content = "".join(text_parts)

    if not isinstance(content, str):
        raise RuntimeError("GitHub Models の応答形式が想定外です。")

    return json.loads(content)


def write_jsonl(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(records: list[dict[str, Any]], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "tweet_url",
        "created_at",
        "author_name",
        "author_username",
        "event_name",
        "normalized_event_name",
        "organization",
        "venue_name",
        "location",
        "normalized_venue_name",
        "normalized_location",
        "start_date",
        "end_date",
        "start_time",
        "category",
        "content_type",
        "is_theater_related",
        "is_recruitment",
        "confidence",
        "is_noise",
        "noise_reason",
        "exclusion_reason",
        "reasoning",
        "source_text",
    ]
    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)


def normalize_record(source_row: dict[str, str], extracted: dict[str, Any]) -> dict[str, Any]:
    record = {
        "tweet_url": source_row.get("tweet_url", ""),
        "created_at": source_row.get("created_at", ""),
        "author_name": source_row.get("author_name", ""),
        "author_username": source_row.get("author_username", ""),
        "event_name": extracted.get("event_name"),
        "normalized_event_name": extracted.get("normalized_event_name") or extracted.get("event_name"),
        "organization": extracted.get("organization"),
        "venue_name": extracted.get("venue_name"),
        "location": extracted.get("location"),
        "start_date": extracted.get("start_date"),
        "end_date": extracted.get("end_date"),
        "start_time": extracted.get("start_time"),
        "category": extracted.get("category"),
        "content_type": extracted.get("content_type"),
        "is_theater_related": extracted.get("is_theater_related"),
        "is_recruitment": extracted.get("is_recruitment"),
        "confidence": extracted.get("confidence"),
        "exclusion_reason": extracted.get("exclusion_reason"),
        "reasoning": extracted.get("reasoning"),
        "source_text": source_row.get("text", ""),
    }
    record["normalized_venue_name"] = normalize_venue_name(record.get("venue_name"))
    record["normalized_location"] = normalize_location(record.get("location"), record.get("normalized_venue_name"), record.get("source_text"))
    noise, noise_reason = classify_noise(record)
    record["is_noise"] = noise
    record["noise_reason"] = noise_reason
    return record


def normalize_venue_name(venue_name: Any) -> str | None:
    if not venue_name:
        return None
    normalized = str(venue_name).strip().replace("　", " ")
    compact = normalized.lower().replace(" ", "")
    for alias, canonical in VENUE_ALIASES.items():
        if alias in compact:
            return canonical
    return normalized


def normalize_location(location: Any, normalized_venue_name: Any, source_text: Any) -> str | None:
    candidates = [location, normalized_venue_name, source_text]
    joined = " ".join(str(candidate or "") for candidate in candidates)
    joined = joined.replace(",", " ").replace("、", " ")

    matched: list[str] = []
    for alias, canonical in CITY_ALIASES.items():
        if alias in joined and canonical not in matched:
            matched.append(canonical)

    if not matched:
        cleaned = str(location or "").strip()
        return cleaned or None
    if len(matched) == 1:
        return matched[0]
    return " / ".join(matched)


def classify_noise(record: dict[str, Any]) -> tuple[bool, str]:
    source_text = str(record.get("source_text") or "")
    category = str(record.get("category") or "")
    content_type = str(record.get("content_type") or "")
    confidence = float(record.get("confidence") or 0)
    author_name = str(record.get("author_name") or "")
    organization = str(record.get("organization") or "")
    normalized_venue_name = str(record.get("normalized_venue_name") or "")
    is_theater_related = record.get("is_theater_related")

    if isinstance(is_theater_related, str):
        is_theater_related = is_theater_related.strip().lower() == "true"

    if is_theater_related is False:
        return True, "non_theater_content"

    if content_type and content_type != "演劇":
        return True, f"content_type_{content_type}"

    if category == "その他":
        return True, "category_is_other"

    if any(pattern in source_text for pattern in NOISE_TEXT_PATTERNS):
        if not any(pattern in source_text for pattern in THEATER_TEXT_PATTERNS):
            return True, "matched_noise_pattern"

    if confidence < 0.55:
        return True, "low_confidence"

    if any(pattern in source_text for pattern in REPORT_TEXT_PATTERNS):
        if not normalized_venue_name and not organization:
            return True, "matched_report_pattern"

    if any(pattern in author_name for pattern in ["委員会", "赤旗", "速報bot"]):
        if not normalized_venue_name:
            return True, "news_or_bot_source"

    has_event_signal = any(
        record.get(field)
        for field in ["event_name", "organization", "venue_name", "start_date", "start_time"]
    )
    if not has_event_signal:
        return True, "missing_event_signal"

    return False, ""


def extract_row(
    index: int,
    total: int,
    row: dict[str, str],
    github_token: str,
    api_version: str,
    model: str,
) -> dict[str, Any]:
    print(f"extracting: {index}/{total} {row.get('tweet_url', '')}")
    prompt = build_user_prompt(row)
    response_payload = call_github_models(github_token, api_version, model, prompt)
    extracted = extract_json_content(response_payload)
    return normalize_record(row, extracted)


def main() -> int:
    load_dotenv(DEFAULT_ENV_FILE)
    args = parse_args()

    github_token = get_github_models_token()
    api_version = os.getenv("GITHUB_MODELS_API_VERSION", DEFAULT_API_VERSION).strip() or DEFAULT_API_VERSION
    if not github_token:
        print("GH_MODELS_TOKEN または GITHUB_TOKEN が見つかりません。.env または Actions secrets に設定してください。", file=sys.stderr)
        return 1

    input_csv = Path(args.input_csv)
    rows = load_rows(input_csv, args.limit)
    total = len(rows)
    structured_records: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(extract_row, index, total, row, github_token, api_version, args.model)
            for index, row in enumerate(rows, start=1)
        ]
        for future in futures:
            structured_records.append(future.result())

    filtered_records = [record for record in structured_records if not record.get("is_noise")]

    write_jsonl(structured_records, Path(args.output_jsonl))
    write_csv(structured_records, Path(args.output_csv))
    write_jsonl(filtered_records, Path(args.filtered_output_jsonl))
    write_csv(filtered_records, Path(args.filtered_output_csv))

    print(f"saved jsonl: {args.output_jsonl}")
    print(f"saved csv: {args.output_csv}")
    print(f"saved filtered jsonl: {args.filtered_output_jsonl}")
    print(f"saved filtered csv: {args.filtered_output_csv}")
    print(f"rows: {len(structured_records)}")
    print(f"filtered_rows: {len(filtered_records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())