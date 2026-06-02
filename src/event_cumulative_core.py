"""build_event_cumulative の純粋ロジック（正規化・キー生成・グルーピング・マージ）。

LLM 呼び出しや I/O はここに置かない。
"""
from __future__ import annotations

import difflib
import re
from datetime import date
from typing import Any


NON_ALNUM_RE = re.compile(r"[^0-9a-zA-Z\u3040-\u30ff\u3400-\u9fff]+")
TITLE_SIMILARITY_THRESHOLD = 0.6
VENUE_GROUP_ALIASES = {
    compact: canonical
    for compact, canonical in {
        "團十郎芸術劇場うらら": "小松市團十郎芸術劇場うらら",
        "團十郎芸術劇場うらら大ホール": "小松市團十郎芸術劇場うらら",
        "小松市團十郎芸術劇場うらら": "小松市團十郎芸術劇場うらら",
        "小松市團十郎芸術劇場うらら大ホール": "小松市團十郎芸術劇場うらら",
    }.items()
}

MERGE_FIELDS = [
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
    "is_event_announcement",
    "is_impression_or_review",
    "is_past_event_reference",
    "has_actionable_schedule_info",
    "requires_link_or_image_context",
    "posting_recommendation",
    "posting_reason",
    "reasoning",
    "source_text",
    "author_name",
    "author_username",
]


def compact_text(value: str) -> str:
    cleaned = NON_ALNUM_RE.sub("", value.strip().lower())
    return cleaned


def normalize_venue_group_key(value: str) -> str:
    compacted = compact_text(value)
    if not compacted:
        return ""
    for alias, canonical in VENUE_GROUP_ALIASES.items():
        if alias in compacted:
            return compact_text(canonical)
    return compacted


def build_event_key(row: dict[str, str]) -> str:
    event_name = compact_text(row.get("normalized_event_name") or row.get("event_name") or "")
    organization = compact_text(row.get("organization") or "")
    venue_name = normalize_venue_group_key(row.get("normalized_venue_name") or row.get("venue_name") or "")
    location = compact_text(row.get("normalized_location") or row.get("location") or "")
    start_date = (row.get("start_date") or "").strip()
    end_date = (row.get("end_date") or "").strip()
    start_time = (row.get("start_time") or "").strip()
    category = (row.get("category") or "").strip()

    if event_name:
        primary = [event_name, organization, venue_name, start_date, end_date, start_time]
    else:
        primary = [organization, venue_name, location, start_date, end_date, start_time, category]
    return "|".join(primary)


def slugify(value: str, fallback_prefix: str, fallback_number: int) -> str:
    cleaned = NON_ALNUM_RE.sub("-", value.strip().lower()).strip("-")
    if cleaned:
        return cleaned
    return f"{fallback_prefix}-{fallback_number:04d}"


def row_quality(row: dict[str, str]) -> tuple[float, int, int, str]:
    confidence = float(row.get("confidence") or 0)
    signal_count = sum(1 for field in MERGE_FIELDS if (row.get(field) or "").strip())
    text_length = len((row.get("source_text") or "").strip())
    created_at = (row.get("created_at") or "").strip()
    return confidence, signal_count, text_length, created_at


def choose_value(current: str, candidate: str) -> str:
    current_value = (current or "").strip()
    candidate_value = (candidate or "").strip()
    if not current_value:
        return candidate_value
    if not candidate_value:
        return current_value
    if len(candidate_value) > len(current_value):
        return candidate_value
    return current_value


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None

    cleaned = str(value).strip().lower()
    if cleaned in {"true", "1", "yes"}:
        return True
    if cleaned in {"false", "0", "no"}:
        return False
    return None


def bool_to_csv(value: bool | None) -> str:
    if value is True:
        return "True"
    if value is False:
        return "False"
    return ""


def recommendation_rank(value: Any) -> int:
    cleaned = str(value or "").strip().lower()
    if cleaned == "post":
        return 3
    if cleaned == "review":
        return 2
    if cleaned == "skip":
        return 1
    return 0


def choose_group_posting_recommendation(records: list[dict[str, Any]]) -> tuple[str, str]:
    best_record: dict[str, Any] | None = None
    best_score: tuple[int, tuple[float, int, int, str]] | None = None

    for record in records:
        score = (recommendation_rank(record.get("posting_recommendation")), row_quality(record))
        if best_score is None or score > best_score:
            best_record = record
            best_score = score

    if best_record is None:
        return "", ""

    return (
        str(best_record.get("posting_recommendation") or "").strip().lower(),
        str(best_record.get("posting_reason") or "").strip(),
    )


def title_similarity(left: str, right: str) -> float:
    normalized_left = compact_text(left)
    normalized_right = compact_text(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return difflib.SequenceMatcher(None, normalized_left, normalized_right).ratio()


def titles_are_similar(left: str, right: str) -> bool:
    normalized_left = compact_text(left)
    normalized_right = compact_text(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    if normalized_left in normalized_right or normalized_right in normalized_left:
        shorter = min(len(normalized_left), len(normalized_right))
        longer = max(len(normalized_left), len(normalized_right))
        if shorter >= max(6, int(longer * 0.5)):
            return True
    return title_similarity(left, right) >= TITLE_SIMILARITY_THRESHOLD


def build_similarity_clusters(records: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    remaining_records = list(records)

    while remaining_records:
        seed = remaining_records.pop(0)
        cluster = [seed]
        changed = True

        while changed:
            changed = False
            next_remaining: list[dict[str, Any]] = []
            for candidate in remaining_records:
                candidate_title = str(candidate.get("normalized_event_name") or candidate.get("event_name") or "")
                if any(
                    titles_are_similar(
                        candidate_title,
                        str(member.get("normalized_event_name") or member.get("event_name") or ""),
                    )
                    for member in cluster
                ):
                    cluster.append(candidate)
                    changed = True
                else:
                    next_remaining.append(candidate)
            remaining_records = next_remaining

        clusters.append(cluster)

    return clusters


def secondary_group_key(record: dict[str, Any]) -> str:
    start_date = (record.get("start_date") or "").strip()
    category = (record.get("category") or "").strip()
    venue_name = normalize_venue_group_key(record.get("normalized_venue_name") or record.get("venue_name") or "")
    organization = compact_text(record.get("organization") or "")

    if not start_date:
        return ""
    month_bucket = start_date[:7]
    if venue_name:
        anchor = f"venue:{venue_name}"
    elif organization:
        anchor = f"org:{organization}"
    else:
        return ""
    return "|".join([month_bucket, category, anchor])


def merge_date_range(records: list[dict[str, Any]]) -> tuple[str, str]:
    start_dates = sorted({(record.get("start_date") or "").strip() for record in records if (record.get("start_date") or "").strip()})
    end_dates = sorted({(record.get("end_date") or "").strip() for record in records if (record.get("end_date") or "").strip()})
    merged_start = start_dates[0] if start_dates else ""
    merged_end = end_dates[-1] if end_dates else ""
    if merged_start and not merged_end:
        merged_end = merged_start
    if merged_end and not merged_start:
        merged_start = merged_end
    return merged_start, merged_end


def choose_canonical_name(records: list[dict[str, Any]], suggested_name: str) -> str:
    canonical = (suggested_name or "").strip()
    if canonical:
        return canonical
    candidates = [
        (record.get("normalized_event_name") or record.get("event_name") or "").strip()
        for record in records
    ]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return ""
    return max(candidates, key=len)


def apply_event_aliases(
    records: list[dict[str, Any]],
    alias_pairs: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """canonical_event_id ← alias_event_id の対応で重複公演をマージする。

    canonical 側の event_id をそのまま残し、alias 側の record を捨てて
    マージ済み 1 行に置き換える。両 id が現存する場合のみ動く。
    """
    if not alias_pairs:
        return records

    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        event_id = str(record.get("event_id") or "").strip()
        if event_id:
            by_id[event_id] = record

    canonical_to_aliases: dict[str, list[str]] = {}
    for canonical, alias in alias_pairs:
        canonical = canonical.strip()
        alias = alias.strip()
        if not canonical or not alias or canonical == alias:
            continue
        if canonical not in by_id or alias not in by_id:
            continue
        canonical_to_aliases.setdefault(canonical, []).append(alias)

    if not canonical_to_aliases:
        return records

    dropped_ids: set[str] = set()
    for aliases in canonical_to_aliases.values():
        dropped_ids.update(aliases)

    new_records: list[dict[str, Any]] = []
    for record in records:
        event_id = str(record.get("event_id") or "").strip()
        if event_id in dropped_ids:
            continue
        aliases = canonical_to_aliases.get(event_id)
        if not aliases:
            new_records.append(record)
            continue
        group = [record] + [by_id[alias_id] for alias_id in aliases]
        canonical_name = str(record.get("normalized_event_name") or record.get("event_name") or "")
        merged = merge_event_group(group, canonical_name)
        merged["event_id"] = event_id
        merged["event_key"] = build_event_key(merged)
        new_records.append(merged)
    return new_records


def merge_event_group(records: list[dict[str, Any]], canonical_name: str) -> dict[str, Any]:
    best_record = max(records, key=row_quality)
    merged = dict(best_record)
    source_tweet_urls: set[str] = set()
    source_author_usernames: set[str] = set()
    first_seen = ""
    last_seen = ""
    max_confidence = 0.0

    for record in records:
        for field in MERGE_FIELDS:
            merged[field] = choose_value(str(merged.get(field) or ""), str(record.get(field) or ""))

        for tweet_url in str(record.get("source_tweet_urls") or record.get("tweet_url") or "").split(" | "):
            cleaned = tweet_url.strip()
            if cleaned:
                source_tweet_urls.add(cleaned)

        for username in str(record.get("source_author_usernames") or record.get("author_username") or "").split(" | "):
            cleaned = username.strip()
            if cleaned:
                source_author_usernames.add(cleaned)

        created_at = str(record.get("created_at") or "").strip()
        first_seen_candidate = str(record.get("first_seen_created_at") or created_at).strip()
        last_seen_candidate = str(record.get("last_seen_created_at") or created_at).strip()
        if first_seen_candidate and (not first_seen or first_seen_candidate < first_seen):
            first_seen = first_seen_candidate
        if last_seen_candidate and (not last_seen or last_seen_candidate > last_seen):
            last_seen = last_seen_candidate

        confidence = float(record.get("confidence") or 0)
        if confidence > max_confidence:
            max_confidence = confidence

    merged["normalized_event_name"] = choose_canonical_name(records, canonical_name)
    merged_start_date, merged_end_date = merge_date_range(records)
    merged["start_date"] = merged_start_date
    merged["end_date"] = merged_end_date
    merged["tweet_url"] = sorted(source_tweet_urls)[0] if source_tweet_urls else str(merged.get("tweet_url") or "")
    merged["created_at"] = last_seen or str(merged.get("created_at") or "")
    merged["confidence"] = max_confidence
    merged["source_tweet_count"] = len(source_tweet_urls)
    merged["source_tweet_urls"] = " | ".join(sorted(source_tweet_urls))
    merged["source_author_usernames"] = " | ".join(sorted(source_author_usernames))
    merged["first_seen_created_at"] = first_seen
    merged["last_seen_created_at"] = last_seen
    merged["is_event_announcement"] = bool_to_csv(any(parse_bool(record.get("is_event_announcement")) is True for record in records))
    merged["is_impression_or_review"] = bool_to_csv(any(parse_bool(record.get("is_impression_or_review")) is True for record in records))
    merged["is_past_event_reference"] = bool_to_csv(any(parse_bool(record.get("is_past_event_reference")) is True for record in records))
    merged["has_actionable_schedule_info"] = bool_to_csv(any(parse_bool(record.get("has_actionable_schedule_info")) is True for record in records))
    merged["requires_link_or_image_context"] = bool_to_csv(any(parse_bool(record.get("requires_link_or_image_context")) is True for record in records))
    merged["posting_recommendation"], merged["posting_reason"] = choose_group_posting_recommendation(records)
    return merged


def build_preview_group_key(record: dict[str, Any]) -> str:
    event_name = str(record.get("normalized_event_name") or record.get("event_name") or "").strip()
    if not event_name:
        return ""

    organization = compact_text(record.get("organization") or "")
    venue_name = normalize_venue_group_key(record.get("normalized_venue_name") or record.get("venue_name") or "")

    if organization:
        return "|".join([compact_text(event_name), f"org:{organization}"])
    if venue_name:
        return "|".join([compact_text(event_name), f"venue:{venue_name}"])
    return ""


def preview_record_priority(record: dict[str, Any]) -> tuple[int, int, int, int, int, str]:
    venue_name = str(record.get("normalized_venue_name") or record.get("venue_name") or "").strip()
    start_date = str(record.get("start_date") or "").strip()
    end_date = str(record.get("end_date") or "").strip()
    start_time = str(record.get("start_time") or "").strip()
    source_tweet_count = int(record.get("source_tweet_count") or 0)
    source_text_length = len(str(record.get("source_text") or "").strip())
    has_multi_day_range = int(bool(start_date and end_date and start_date != end_date))
    has_venue = int(bool(venue_name))
    has_start_time = int(bool(start_time))
    return (has_venue, has_multi_day_range, has_start_time, source_tweet_count, source_text_length, start_date)


def parse_iso_date(value: str) -> date | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        return None


def parse_created_at_date(value: str) -> date | None:
    cleaned = value.strip()
    if len(cleaned) < 10:
        return None
    return parse_iso_date(cleaned[:10])


def is_preview_subsumed(candidate: dict[str, Any], canonical: dict[str, Any]) -> bool:
    candidate_venue = str(candidate.get("normalized_venue_name") or candidate.get("venue_name") or "").strip()
    canonical_venue = str(canonical.get("normalized_venue_name") or canonical.get("venue_name") or "").strip()

    if not candidate_venue and canonical_venue:
        return True
    if candidate_venue and canonical_venue and candidate_venue != canonical_venue:
        return False

    candidate_start = str(candidate.get("start_date") or "").strip()
    candidate_end = str(candidate.get("end_date") or "").strip() or candidate_start
    canonical_start = str(canonical.get("start_date") or "").strip()
    canonical_end = str(canonical.get("end_date") or "").strip() or canonical_start
    if candidate_start and candidate_end and canonical_start and canonical_end:
        if canonical_start <= candidate_start and canonical_end >= candidate_end:
            return preview_record_priority(canonical) > preview_record_priority(candidate)

    if candidate_start or candidate_end or not canonical_start or not canonical_end:
        return False

    if candidate_venue:
        return False

    candidate_seen_date = parse_created_at_date(str(candidate.get("last_seen_created_at") or candidate.get("created_at") or ""))
    canonical_seen_date = parse_created_at_date(str(canonical.get("last_seen_created_at") or canonical.get("created_at") or ""))
    canonical_start_date = parse_iso_date(canonical_start)
    if not candidate_seen_date or not canonical_seen_date or not canonical_start_date:
        return False

    if abs((canonical_seen_date - candidate_seen_date).days) > 120:
        return False

    if canonical_start_date < candidate_seen_date:
        return False

    return preview_record_priority(canonical) > preview_record_priority(candidate)


def suppress_preview_like_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped_records: dict[str, list[dict[str, Any]]] = {}
    passthrough_records: list[dict[str, Any]] = []

    for record in records:
        group_key = build_preview_group_key(record)
        if not group_key:
            passthrough_records.append(record)
            continue
        grouped_records.setdefault(group_key, []).append(record)

    filtered_records = list(passthrough_records)
    for group in grouped_records.values():
        kept_records: list[dict[str, Any]] = []
        for record in sorted(group, key=preview_record_priority, reverse=True):
            if any(is_preview_subsumed(record, kept_record) for kept_record in kept_records):
                continue
            kept_records.append(record)
        filtered_records.extend(kept_records)

    return filtered_records


def renumber_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sorted_records = sorted(
        records,
        key=lambda item: ((item.get("last_seen_created_at") or item.get("created_at") or ""), build_event_key(item)),
        reverse=True,
    )

    normalized_records: list[dict[str, Any]] = []
    for index, record in enumerate(sorted_records, start=1):
        normalized_record = dict(record)
        normalized_record["event_key"] = build_event_key(normalized_record)
        id_seed = (
            (normalized_record.get("normalized_event_name") or "").strip()
            or (normalized_record.get("event_name") or "").strip()
            or (normalized_record.get("organization") or "").strip()
            or (normalized_record.get("normalized_venue_name") or normalized_record.get("venue_name") or "").strip()
            or normalized_record["event_key"]
        )
        normalized_record["event_id"] = f"event-{slugify(id_seed, 'event', index)}"
        normalized_records.append(normalized_record)
    return normalized_records


def build_event_records(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}

    for row in rows:
        if str(row.get("is_noise") or "").lower() == "true":
            continue

        event_key = build_event_key(row)
        if not event_key.replace("|", ""):
            continue

        bucket = buckets.setdefault(
            event_key,
            {
                "event_key": event_key,
                "best_row": row,
                "best_score": row_quality(row),
                "source_tweet_urls": set(),
                "source_author_usernames": set(),
                "first_seen_created_at": (row.get("created_at") or "").strip(),
                "last_seen_created_at": (row.get("created_at") or "").strip(),
                "max_confidence": float(row.get("confidence") or 0),
            },
        )

        tweet_url = (row.get("tweet_url") or "").strip()
        if tweet_url:
            bucket["source_tweet_urls"].add(tweet_url)

        author_username = (row.get("author_username") or "").strip()
        if author_username:
            bucket["source_author_usernames"].add(author_username)

        created_at = (row.get("created_at") or "").strip()
        if created_at:
            if not bucket["first_seen_created_at"] or created_at < bucket["first_seen_created_at"]:
                bucket["first_seen_created_at"] = created_at
            if not bucket["last_seen_created_at"] or created_at > bucket["last_seen_created_at"]:
                bucket["last_seen_created_at"] = created_at

        confidence = float(row.get("confidence") or 0)
        if confidence > bucket["max_confidence"]:
            bucket["max_confidence"] = confidence

        candidate_score = row_quality(row)
        if candidate_score > bucket["best_score"]:
            bucket["best_row"] = row
            bucket["best_score"] = candidate_score

        best_row = bucket["best_row"]
        for field in MERGE_FIELDS:
            best_row[field] = choose_value(best_row.get(field) or "", row.get(field) or "")

    records: list[dict[str, Any]] = []
    for index, bucket in enumerate(
        sorted(buckets.values(), key=lambda item: (item["last_seen_created_at"], item["event_key"]), reverse=True),
        start=1,
    ):
        best_row = dict(bucket["best_row"])
        event_name = (best_row.get("event_name") or "").strip()
        normalized_event_name = (best_row.get("normalized_event_name") or event_name).strip()
        organization = (best_row.get("organization") or "").strip()
        venue_name = (best_row.get("normalized_venue_name") or best_row.get("venue_name") or "").strip()
        id_seed = normalized_event_name or event_name or organization or venue_name or bucket["event_key"]

        records.append(
            {
                "event_id": f"event-{slugify(id_seed, 'event', index)}",
                "event_key": bucket["event_key"],
                "tweet_url": sorted(bucket["source_tweet_urls"])[0] if bucket["source_tweet_urls"] else "",
                "created_at": bucket["last_seen_created_at"],
                "author_name": (best_row.get("author_name") or "").strip(),
                "author_username": (best_row.get("author_username") or "").strip(),
                "event_name": event_name,
                "normalized_event_name": normalized_event_name,
                "organization": organization,
                "venue_name": (best_row.get("venue_name") or "").strip(),
                "location": (best_row.get("location") or "").strip(),
                "normalized_venue_name": (best_row.get("normalized_venue_name") or "").strip(),
                "normalized_location": (best_row.get("normalized_location") or "").strip(),
                "start_date": (best_row.get("start_date") or "").strip(),
                "end_date": (best_row.get("end_date") or "").strip(),
                "start_time": (best_row.get("start_time") or "").strip(),
                "category": (best_row.get("category") or "").strip(),
                "is_recruitment": (best_row.get("is_recruitment") or "").strip(),
                "is_event_announcement": (best_row.get("is_event_announcement") or "").strip(),
                "is_impression_or_review": (best_row.get("is_impression_or_review") or "").strip(),
                "is_past_event_reference": (best_row.get("is_past_event_reference") or "").strip(),
                "has_actionable_schedule_info": (best_row.get("has_actionable_schedule_info") or "").strip(),
                "requires_link_or_image_context": (best_row.get("requires_link_or_image_context") or "").strip(),
                "posting_recommendation": (best_row.get("posting_recommendation") or "").strip(),
                "posting_reason": (best_row.get("posting_reason") or "").strip(),
                "confidence": bucket["max_confidence"],
                "reasoning": (best_row.get("reasoning") or "").strip(),
                "source_text": (best_row.get("source_text") or "").strip(),
                "source_tweet_count": len(bucket["source_tweet_urls"]),
                "source_tweet_urls": " | ".join(sorted(bucket["source_tweet_urls"])),
                "source_author_usernames": " | ".join(sorted(bucket["source_author_usernames"])),
                "first_seen_created_at": bucket["first_seen_created_at"],
                "last_seen_created_at": bucket["last_seen_created_at"],
            }
        )
    return records
