# 北陸演劇情報収集

石川県の演劇関連投稿を、重要クエリだけで収集する最小構成です。

## 現在の推奨方式

X の free plan では recent search API が使えないため、現在はブラウザ自動操作版を優先します。

## ブラウザ版の使い方

1. `.env.example` を参考に `.env` を作成する
2. `.env` に `X_LOGIN_IDENTIFIER` と `X_LOGIN_PASSWORD` を設定する
3. 必要なら `X_USERNAME` を設定する
4. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/fetch_x_posts_browser.py` を実行する

互換のため、既存の `X_CLIENT_ID` と `X_CLIENT_PASSW0RD` も読めます。

headless 実行が必要なら `--headless` を付けられますが、X 側の一時エラー画面が出る場合は通常表示での実行が安定します。

## API版

`src/fetch_x_posts.py` は Bearer Token を使う API 版です。free plan では 403 になる可能性があります。

## GitHub Models で構造化抽出

収集済み CSV から日時や場所などを抜き出すには、GitHub Models 版を使えます。

1. `.env` に `GITHUB_TOKEN` を設定する
2. 必要なら `GITHUB_MODELS_MODEL` を設定する
3. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/extract_events_github_models.py --limit 5` を実行する

出力先:

- `data/output/structured_events.jsonl`
- `data/output/structured_events.csv`
- `data/output/structured_events_filtered.jsonl`
- `data/output/structured_events_filtered.csv`

補足:

- `structured_events.*` は生の抽出結果です
- `structured_events_filtered.*` はノイズ除去後の結果です
- `normalized_venue_name` と `normalized_location` に正規化結果が入ります

## 劇団・劇場マスター生成

ノイズ除去後のイベント結果から、劇団マスターと劇場マスターを生成できます。

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/build_entity_masters.py` を実行する

出力先:

- `data/output/organization_master.csv`
- `data/output/venue_master.csv`

補足:

- `aliases` に別名候補を入れます
- `event_count` に出現回数を入れます
- `sample_source_url` から元投稿をたどれます

## スケジュール一覧生成

スケジュール確認用に、イベント名、劇団名、劇場名、公演日程、参照先URLを並べた一覧を生成できます。

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/build_schedule_list.py` を実行する

出力先:

- `data/output/schedule_list.csv`

補足:

- `official_reference_url` はマスターの公式サイトや公式Xを優先します
- 未登録の場合はイベント投稿者の X プロフィールを候補として使います

## Webで見る

ローカルでブラウザ表示するだけなら、静的ページを同梱してあるので HTTP サーバーで開けます。

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/build_schedule_list.py` を実行する
2. ワークスペース直下で `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe -m http.server 8000` を実行する
3. ブラウザで `http://localhost:8000/web/` を開く

補足:

- ページ本体は `web/` にあります
- データは `data/output/schedule_list.json` を読み込みます
- そのまま GitHub Pages や Cloudflare Pages に置きたい場合も、同じ静的ファイル構成を流用できます

## 一括実行

情報収集から構造化抽出、マスター生成、スケジュール生成までを 1 コマンドで順番に実行できます。

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/run_pipeline.py`

既存の収集済みCSVから再実行したい場合:

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/run_pipeline.py --skip-collect --input-csv data/output/x_browser_search_20260508_124323.csv`

補足:

- 収集ステップは X の手動ログイン待機を含みます
- 抽出ステップでは `.env` の `GITHUB_TOKEN` が必要です
- 同じ `tweet_url` は累積CSVに重複追加せず、新しい投稿だけを追加します
- 累積データは `data/output/structured_events_cumulative.csv` と `data/output/structured_events_filtered_cumulative.csv` に保存されます
- イベント単位の統合結果は `data/output/event_cumulative.csv` に保存されます
- 最後にイベント単位データから `data/output/schedule_list.csv` と `docs/data/schedule_list.json` を更新します

公開用 JSON の commit と push まで含めたい場合:

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/run_pipeline.py --publish`

補足:

- `--publish` は `docs/data/schedule_list.json` に差分がある時だけ commit と push を行います
- コミット文言を固定したい場合は `--commit-message "Update published schedule data"` を付けられます

## GitHub Pages で公開する

GitHub Pages 用の公開ファイルは `docs/` に出力します。`docs/` はそのまま Pages の公開元に使えます。

1. `c:/Users/psych/Dropbox/北陸演劇情報収集/.venv/Scripts/python.exe src/build_schedule_list.py` を実行する
2. `docs/data/schedule_list.json` が更新されることを確認する
3. GitHub に push する
4. GitHub の Settings > Pages で Branch を `main`、Folder を `/docs` に設定する

公開後の構成:

- `docs/index.html` がトップページになります
- `docs/app.js` と `docs/styles.css` が画面を構成します
- `docs/data/schedule_list.json` が公開データです

注意:

- `docs/data/schedule_list.json` は公開ファイルなので、載せたデータは誰でも見られます
- X 収集や GitHub Models 抽出は GitHub Pages 上では動かず、ローカルで生成してから push する運用です

## 出力

- CSV は `data/output/` に保存されます
- 重要クエリ一覧は `config/priority_queries.json` です
- ログイン状態は `data/session/` に保存されます