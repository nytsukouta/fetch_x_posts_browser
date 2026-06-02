# 公開データスキーマ

`docs/data/` の JSON は GitHub Pages で配信されます。手動編集せず、`src/run_pipeline.py` 経由で再生成してください。

## schedule_list.json

生成元: [src/build_schedule_list.py](../src/build_schedule_list.py)

```jsonc
{
  "generated_at": "2026-05-31T12:34:56+09:00",   // ISO8601 (JST)
  "total_count": 42,                              // items 配列の件数
  "items": [
    {
      "event_id": "event-xxxx",                   // event_cumulative.csv の event_id
      "event_name": "公演タイトル",
      "normalized_event_name": "公演タイトル",     // 揺れ吸収済み名称
      "organization": "劇団名",
      "venue_name": "会場名",
      "normalized_venue_name": "正規化会場名",
      "location": "市区町村など",
      "start_date": "2026-06-01",                 // ISO 日付 (YYYY-MM-DD), 未確定なら空
      "end_date": "2026-06-02",
      "start_time": "19:00",                       // HH:MM, 未確定なら空
      "category": "演劇 | 朗読 | ミュージカル...",
      "tweet_url": "https://x.com/.../status/...",  // 代表 URL
      "source_tweet_urls": "url1 | url2",          // " | " 区切り
      "source_tweet_count": 3,
      "official_reference_url": "https://...",     // マスター優先, 無ければ投稿者プロフィール
      "posting_recommendation": "post | review | skip",
      "first_seen_created_at": "2026-05-20T...",
      "last_seen_created_at": "2026-05-29T..."
    }
  ]
}
```

不変条件:
- `event_id` はファイル内一意
- `start_date` <= `end_date`（両方ある場合）
- `items` は `start_date` 昇順、`start_date` 同値なら `event_name` 昇順

## master_data.json

生成元: [src/build_master_pages_data.py](../src/build_master_pages_data.py)

```jsonc
{
  "generated_at": "2026-05-31T12:34:56+09:00",
  "organizations": [
    {
      "name": "劇団名",
      "aliases": ["別表記1", "別表記2"],
      "official_url": "https://...",
      "official_x": "https://x.com/...",
      "notes": "任意の補足"
    }
  ],
  "venues": [
    {
      "name": "会場名",
      "address": "石川県金沢市...",
      "official_url": "https://...",
      "notes": "任意の補足"
    }
  ]
}
```

## excluded_tweet_ids.csv

生成元: [src/build_excluded_tweet_ids.py](../src/build_excluded_tweet_ids.py)

ヘッダ: `tweet_id, tweet_url, noise_reason, first_seen_created_at`

- 累積CSV (`structured_events_cumulative.csv`) 内で `is_noise=true` と判定された tweet を集約
- `src/fetch_x_posts.py --excluded-ids-csv` で取得結果から事前除外し、保存 CSV を肥大化させない用途

## 互換性ポリシー

- 既存フィールド名・型は破壊的変更を避ける
- 追加は許容、削除は `web/SCHEMA.md` と `web/app.js` を同時更新
