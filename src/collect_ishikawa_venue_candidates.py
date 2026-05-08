from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path
from urllib.parse import urljoin
from urllib import request


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_FILE = ROOT_DIR / "config" / "ishikawa_venue_source_urls.txt"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "ishikawa_venue_candidates_web.csv"

ISHIKAWA_LOCATION_PATTERNS = [
    "石川県",
    "金沢",
    "七尾",
    "小松",
    "白山",
    "加賀",
    "野々市",
    "能美",
    "かほく",
    "羽咋",
    "珠洲",
    "輪島",
    "能登",
    "津幡",
    "内灘",
    "志賀",
    "中能登",
    "宝達志水",
    "穴水",
    "川北",
]

VENUE_INCLUDE_PATTERNS = [
    "劇場",
    "演劇堂",
    "ドラマ工房",
    "文化ホール",
    "文化会館",
    "能楽堂",
    "芸術村",
    "ホール",
]

VENUE_EXCLUDE_PATTERNS = [
    "映画",
    "シネマ",
    "ライブ",
    "LIVE",
    "コンサート",
    "ミュージアム",
    "美術館",
    "博物館",
    "図書館",
    "体育館",
    "アイドル",
]

GENERIC_NAME_PATTERNS = [
    "一覧",
    "情報",
    "年間公演",
    "公演情報",
    "イベント",
    "募集",
    "会員募集",
    "について",
    "更新",
    "アクセス",
    "施設概要",
    "公式サイト",
    "オープンサロン",
    "ボランティア",
    "日本の",
    "石川県の劇場",
    "石川県内にある劇場",
    "石川県所在の劇場",
    "劇場・ホール",
    "石川県の 劇場",
    "石川県七尾市の演劇ホール",
    "ちょっと一息 芸術村",
    "年度 能登演劇堂",
    "加賀市山代にあります",
    "市町文化会館",
    "市市文化会館",
    "お仕事図鑑",
    "ご希望の劇場",
    "音楽ホール",
]

GENERIC_PREFIX_PATTERNS = [
    "ここ",
    "その",
    "という",
    "が",
    "を",
    "かなり",
    "気になる",
    "なにしろ",
    "トに",
    "ジで",
]

ANCHOR_RE = re.compile(r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<label>.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
SPACE_RE = re.compile(r"[ \t\u3000]+")
VENUE_TEXT_RE = re.compile(
    r"([一-龯ぁ-んァ-ヶA-Za-z0-9&'’!！?？・/（）()\-\s]{2,60}?(?:劇場|演劇堂|ドラマ工房|文化ホール|文化会館|能楽堂|芸術村|ホール))"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Ishikawa venue candidates from manually curated source URLs")
    parser.add_argument("--source-file", default=str(DEFAULT_SOURCE_FILE), help="候補収集元URL一覧のテキストファイル")
    parser.add_argument("--output-csv", default=str(DEFAULT_OUTPUT_CSV), help="候補CSVの保存先")
    parser.add_argument("--timeout", type=int, default=20, help="各ページ取得のタイムアウト秒")
    return parser.parse_args()


def load_source_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    urls: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def fetch_html(url: str, timeout: int) -> str:
    api_request = request.Request(url, headers={"User-Agent": "Mozilla/5.0 venue-candidate-collector"})
    with request.urlopen(api_request, timeout=timeout) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def strip_html(raw_html: str) -> str:
    cleaned = SCRIPT_RE.sub(" ", raw_html)
    cleaned = re.sub(r"</(p|div|li|tr|h1|h2|h3|h4|br)>", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = TAG_RE.sub(" ", cleaned)
    cleaned = html.unescape(cleaned)
    lines = []
    for raw_line in cleaned.splitlines():
        line = SPACE_RE.sub(" ", raw_line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def clean_anchor_label(value: str) -> str:
    return SPACE_RE.sub(" ", html.unescape(TAG_RE.sub(" ", value))).strip()


def looks_like_venue(name: str) -> bool:
    if not name:
        return False
    cleaned = name.strip()
    if len(cleaned) < 3 or len(cleaned) > 40:
        return False
    if any(pattern.lower() in name.lower() for pattern in VENUE_EXCLUDE_PATTERNS):
        return False
    if any(pattern in cleaned for pattern in GENERIC_NAME_PATTERNS):
        return False
    if any(cleaned.startswith(pattern) for pattern in GENERIC_PREFIX_PATTERNS):
        return False
    if cleaned.startswith("(") or cleaned.startswith("（"):
        return False
    if any(char in cleaned for char in ["。", "、", "!", "！", "?", "？", "【", "】", "[", "]"]):
        return False
    return any(pattern.lower() in name.lower() for pattern in VENUE_INCLUDE_PATTERNS)


def detect_location_hint(text: str) -> str:
    matched = [pattern for pattern in ISHIKAWA_LOCATION_PATTERNS if pattern in text]
    return " / ".join(dict.fromkeys(matched))


def compute_score(name: str, context: str, href: str) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []
    if any(keyword in name for keyword in ["劇場", "演劇堂", "ドラマ工房", "能楽堂"]):
        score += 3
        reasons.append("strong_venue_keyword")
    elif any(keyword in name for keyword in ["文化ホール", "文化会館", "芸術村", "ホール"]):
        score += 2
        reasons.append("venue_keyword")
    if detect_location_hint(context):
        score += 2
        reasons.append("ishikawa_context")
    if href.startswith("http://") or href.startswith("https://"):
        score += 1
        reasons.append("linked_source")
    return score, "|".join(reasons)


def add_candidate(
    candidates: dict[str, dict[str, str]],
    *,
    name: str,
    context: str,
    source_url: str,
    source_type: str,
    official_website_candidate: str = "",
) -> None:
    normalized_name = normalize_name(name)
    if not normalized_name or not looks_like_venue(name):
        return

    score, reason = compute_score(name, context, official_website_candidate or source_url)
    if score < 2:
        return

    existing = candidates.get(normalized_name)
    row = {
        "candidate_name": name.strip(),
        "location_hint": detect_location_hint(context),
        "official_website_candidate": official_website_candidate,
        "source_url": source_url,
        "source_type": source_type,
        "score": str(score),
        "reason": reason,
    }
    if not existing or should_replace(existing, row):
        candidates[normalized_name] = row


def should_replace(existing: dict[str, str], candidate: dict[str, str]) -> bool:
    existing_score = int(existing.get("score") or 0)
    candidate_score = int(candidate.get("score") or 0)
    if candidate_score != existing_score:
        return candidate_score > existing_score
    if existing.get("source_type") != "anchor" and candidate.get("source_type") == "anchor":
        return True
    return False


def normalize_name(value: str) -> str:
    cleaned = SPACE_RE.sub("", value.strip().lower())
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    return cleaned


def extract_candidates_from_html(raw_html: str, source_url: str) -> list[dict[str, str]]:
    candidates: dict[str, dict[str, str]] = {}
    text = strip_html(raw_html)

    for match in ANCHOR_RE.finditer(raw_html):
        href = urljoin(source_url, html.unescape(match.group("href")).strip())
        label = clean_anchor_label(match.group("label"))
        add_candidate(
            candidates,
            name=label,
            context=f"{label} {source_url}",
            source_url=source_url,
            source_type="anchor",
            official_website_candidate=href,
        )

    for line in text.splitlines():
        if len(line) > 80:
            continue
        for match in VENUE_TEXT_RE.finditer(line):
            name = SPACE_RE.sub(" ", match.group(1)).strip(" ・")
            add_candidate(
                candidates,
                name=name,
                context=line,
                source_url=source_url,
                source_type="text",
            )

    return sorted(candidates.values(), key=lambda row: (-int(row["score"]), row["candidate_name"]))


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "candidate_name",
        "location_hint",
        "official_website_candidate",
        "source_url",
        "source_type",
        "score",
        "reason",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    source_urls = load_source_urls(Path(args.source_file))
    all_rows: list[dict[str, str]] = []

    for source_url in source_urls:
        print(f"fetching: {source_url}")
        try:
            raw_html = fetch_html(source_url, timeout=args.timeout)
        except Exception as exc:
            print(f"failed: {source_url} ({exc})")
            continue
        all_rows.extend(extract_candidates_from_html(raw_html, source_url))

    deduped: dict[str, dict[str, str]] = {}
    for row in all_rows:
        key = normalize_name(row["candidate_name"])
        existing = deduped.get(key)
        if not existing or int(existing["score"]) < int(row["score"]):
            deduped[key] = row

    rows = sorted(deduped.values(), key=lambda row: (-int(row["score"]), row["candidate_name"]))
    write_csv(Path(args.output_csv), rows)
    print(f"saved candidate csv: {args.output_csv}")
    print(f"rows: {len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())