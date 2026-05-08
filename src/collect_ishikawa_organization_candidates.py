from __future__ import annotations

import argparse
import csv
import html
import re
from pathlib import Path
from urllib import request
from urllib.parse import urljoin


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_FILE = ROOT_DIR / "config" / "ishikawa_organization_source_urls.txt"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "output" / "ishikawa_organization_candidates_web.csv"

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

ORG_INCLUDE_PATTERNS = [
    "劇団",
    "演劇部",
    "演劇人協会",
    "演劇鑑賞会",
    "表現集団",
    "Theater",
    "theater",
]

ORG_EXCLUDE_PATTERNS = [
    "アイドル",
    "オーケストラ",
    "吹奏楽",
    "合唱",
    "ダンス",
    "ライブ",
    "シネマ",
    "映画",
    "文化会館",
    "文化ホール",
    "劇場",
    "能楽堂",
]

GENERIC_NAME_PATTERNS = [
    "一覧",
    "お知らせ",
    "公演情報",
    "イベント情報",
    "アクセス",
    "お問い合わせ",
    "最新情報",
    "過去の公演",
    "加盟団体一覧へ戻る",
    "劇団紹介",
    "スタジオ案内",
    "会員募集",
    "登録団体一覧",
    "劇団員",
    "劇団員募集中",
    "Official Web Site",
    "へようこそ",
    "とは？",
    "を中心に設立された演劇団",
    "金沢から世界へ地域演劇を発信する 劇団",
    "石川県を拠点に活動する演劇団",
    "2026年 劇団",
]

ANCHOR_RE = re.compile(r'<a\b[^>]*href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<label>.*?)</a>', re.IGNORECASE | re.DOTALL)
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
SPACE_RE = re.compile(r"[ \t\u3000]+")
ORG_TEXT_RE = re.compile(
    r"([一-龯ぁ-んァ-ヶA-Za-z0-9&'’!！?？・/（）()\-\s]{2,60}?(?:劇団|演劇部|演劇人協会|演劇鑑賞会|表現集団|Theater|theater))"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect Ishikawa organization candidates from manually curated source URLs")
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
    api_request = request.Request(url, headers={"User-Agent": "Mozilla/5.0 organization-candidate-collector"})
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


def normalize_name(value: str) -> str:
    cleaned = SPACE_RE.sub("", value.strip().lower())
    cleaned = cleaned.replace("（", "(").replace("）", ")")
    cleaned = re.sub(r"[()・/\-]", "", cleaned)
    return cleaned


def looks_like_organization(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < 3 or len(cleaned) > 50:
        return False
    if any(pattern.lower() in cleaned.lower() for pattern in ORG_EXCLUDE_PATTERNS):
        return False
    if any(pattern in cleaned for pattern in GENERIC_NAME_PATTERNS):
        return False
    if any(phrase in cleaned for phrase in ["を中心に設立", "へようこそ", "最新情報", "募集中", "出演 "]):
        return False
    if any(char in cleaned for char in ["。", "、", "【", "】", "[", "]"]):
        return False
    return any(pattern.lower() in cleaned.lower() for pattern in ORG_INCLUDE_PATTERNS)


def detect_location_hint(text: str) -> str:
    matched = [pattern for pattern in ISHIKAWA_LOCATION_PATTERNS if pattern in text]
    return " / ".join(dict.fromkeys(matched))


def compute_score(name: str, context: str, href: str) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []
    if any(keyword in name for keyword in ["劇団", "演劇部", "表現集団"]):
        score += 3
        reasons.append("strong_org_keyword")
    elif any(keyword in name for keyword in ["演劇人協会", "演劇鑑賞会", "Theater", "theater"]):
        score += 2
        reasons.append("org_keyword")
    if detect_location_hint(context):
        score += 2
        reasons.append("ishikawa_context")
    if href.startswith("http://") or href.startswith("https://"):
        score += 1
        reasons.append("linked_source")
    return score, "|".join(reasons)


def should_replace(existing: dict[str, str], candidate: dict[str, str]) -> bool:
    existing_score = int(existing.get("score") or 0)
    candidate_score = int(candidate.get("score") or 0)
    if candidate_score != existing_score:
        return candidate_score > existing_score
    if existing.get("source_type") != "anchor" and candidate.get("source_type") == "anchor":
        return True
    return False


def add_candidate(
    candidates: dict[str, dict[str, str]],
    *,
    name: str,
    context: str,
    source_url: str,
    source_type: str,
    official_website_candidate: str = "",
) -> None:
    if not looks_like_organization(name):
        return

    normalized_name = normalize_name(name)
    score, reason = compute_score(name, context, official_website_candidate or source_url)
    if score < 2:
        return

    row = {
        "candidate_name": name.strip(),
        "location_hint": detect_location_hint(context),
        "official_website_candidate": official_website_candidate,
        "source_url": source_url,
        "source_type": source_type,
        "score": str(score),
        "reason": reason,
    }
    existing = candidates.get(normalized_name)
    if not existing or should_replace(existing, row):
        candidates[normalized_name] = row


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
        if len(line) > 100:
            continue
        for match in ORG_TEXT_RE.finditer(line):
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
