# 公開データスキーマ

`docs/data/` の JSON は GitHub Pages で配信されます。手動編集せず、`src/run_pipeline.py` 経由で再生成してください。

## schedule_list.json

生成元: [src/build_schedule_list.py](../src/build_schedule_list.py)

```jsonc
{
  "generated_at": "2026-05-31T12:34:56+09:00",   // ISO8601 (JST)
  "count": 42,                                    // items 配列の件数
  "items": [
    {
      "event_id": "event-xxxx",                   // event_cumulative.csv の event_id
      "event_name": "公演タイトル",
      "organization_id": "org-xxxx",
      "organization_name": "劇団名",
      "venue_name": "会場名",
      "performance_schedule": "2026-06-01 - 2026-06-02 19:00",
      "official_reference_url": "https://...",     // マスター優先, 無ければ投稿者プロフィール
      "official_reference_type": "organization_official_website",
      "normalized_location": "石川県金沢市 / 石川県", // 詳細表示・検索用
      "source_tweet_url": "https://x.com/.../status/...",
      "prefecture": "石川県"                       // 都道府県フィルター用。判定不能なら空
    }
  ]
}
```

不変条件:
- `event_id` はファイル内一意
- `items` は `performance_schedule` 昇順
- `normalized_location` は詳細地域を保持し、`prefecture` はフィルター用の派生値

## master_data.json

生成元: [src/build_master_pages_data.py](../src/build_master_pages_data.py)

```jsonc
{
  "generated_at": "2026-05-31T12:34:56+09:00",
  "organizations": [
    {
      "id": "org-xxxx",
      "name": "劇団名",
      "location": "石川県金沢市",
      "prefecture": "石川県",
      "official_website": "https://...",
      "official_x": "https://x.com/...",
      "query_include": true
    }
  ],
  "venues": [
    {
      "id": "venue-xxxx",
      "name": "会場名",
      "location": "石川県金沢市...",
      "prefecture": "石川県",
      "official_website": "https://..."
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
