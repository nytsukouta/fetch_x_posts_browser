# 北陸演劇情報収集

石川県の演劇関連投稿を、重要クエリだけで収集する最小構成です。

## 現在の推奨方式

現在は X API 版を優先します。`.env` に `X_BEARER_TOKEN` を設定し、recent search が使える API アクセス権を持つ前提です。

基本フローは次の 4 段階です。

1. `src/build_priority_queries_from_masters.py` で検索クエリを再生成する
2. `src/fetch_x_posts.py` で X recent search API から収集する
3. `src/extract_events_github_models.py` でイベント情報を構造化する
4. `src/build_event_cumulative.py` と `src/build_schedule_list.py` で統合・公開用データを作る

## API版

`src/fetch_x_posts.py` は Bearer Token を使う API 版です。

1. `.env` に `X_BEARER_TOKEN` を設定する
2. `.venv/Scripts/python.exe src/fetch_x_posts.py` を実行する

補足:

- recent search が使えない契約や権限だと 403 になります
- 既定の `max_results_per_query` は 30 件です
- 収集CSVは `data/output/x_recent_search_*.csv` に保存されます

## GitHub Models で構造化抽出

収集済み CSV から日時や場所などを抜き出すには、GitHub Models 版を使えます。

1. `.env` に `GH_MODELS_TOKEN` または `GITHUB_TOKEN` を設定する
2. 必要なら `GITHUB_MODELS_MODEL` を設定する
3. `.venv/Scripts/python.exe src/extract_events_github_models.py --limit 5` を実行する

出力先:

- `data/output/structured_events.csv`
- `data/output/structured_events_filtered.csv`

補足:

- `structured_events.*` は生の抽出結果です
- `structured_events_filtered.*` はノイズ除去後の結果です
- JSONL は通常運用では保存せず、必要な時だけ `--debug-outputs` を付けて保存します
- `organization` は `data/output/organization_master.csv` の `official_x` と正規名に基づいて補正されます
- `normalized_venue_name` と `normalized_location` に正規化結果が入ります

## スケジュール一覧生成

スケジュール確認用に、イベント名、劇団名、劇場名、公演日程、参照先URLを並べた一覧を生成できます。

1. `.venv/Scripts/python.exe src/build_schedule_list.py` を実行する

出力先:

- `data/output/schedule_list.csv`

補足:

- `official_reference_url` はマスターの公式サイトや公式Xを優先します
- 未登録の場合はイベント投稿者の X プロフィールを候補として使います

## Webで見る

ローカルでブラウザ表示するだけなら、静的ページを同梱してあるので HTTP サーバーで開けます。

1. `.venv/Scripts/python.exe src/build_schedule_list.py` を実行する
2. ワークスペース直下で `.venv/Scripts/python.exe -m http.server 8000` を実行する
3. ブラウザで `http://localhost:8000/web/` を開く

補足:

- ページ本体は `web/` にあります
- データは `data/output/schedule_list.json` を読み込みます
- そのまま GitHub Pages や Cloudflare Pages に置きたい場合も、同じ静的ファイル構成を流用できます

## 一括実行

情報収集から構造化抽出、累積統合、スケジュール生成までを 1 コマンドで順番に実行できます。

1. `.venv/Scripts/python.exe src/run_pipeline.py`

既存の収集済みCSVから再実行したい場合:

1. `.venv/Scripts/python.exe src/run_pipeline.py --skip-collect --input-csv data/output/x_recent_search_20260509_173241.csv`

補足:

- 収集ステップは API 版のみで、`.env` の `X_BEARER_TOKEN` が必要です
- 抽出ステップでは `.env` の `GH_MODELS_TOKEN` または `GITHUB_TOKEN` が必要です
- 実行開始時に `src/build_priority_queries_from_masters.py` を自動実行し、最新のマスターから `config/priority_queries.json` を再生成します
- 同じ `tweet_url` は累積CSVに重複追加せず、新しい投稿だけを追加します
- 累積データは `data/output/structured_events_cumulative.csv` と `data/output/structured_events_filtered_cumulative.csv` に保存されます
- イベント単位の統合結果は `data/output/event_cumulative.csv` に保存されます
- 劇団マスターと劇場マスターはパイプラインでは自動更新せず、既存ファイルを参照します
- 最後にイベント単位データから `data/output/schedule_list.csv` と `docs/data/schedule_list.json` を更新します
- 抽出段階の JSONL は通常運用では保存せず、必要な時だけ `--debug-outputs` を付けて保存します

tracked な `config/` や `docs/` を汚さずにローカル確認したい場合:

1. `.venv/Scripts/python.exe src/run_pipeline.py --local-preview-dir`

補足:

- `--local-preview-dir` を付けると `config/priority_queries.json`、`docs/data/schedule_list.json`、`docs/data/master_data.json`、`web/data/master_data.json` を直接更新せず、既定では `data/output/_local_preview/` 配下へ保存します
- 別の保存先を使いたい場合は `--local-preview-dir data/output/my_preview` のように明示できます
- `--publish` とは同時に使えません

マスター運用メモ:

- `data/output/organization_master.csv` の `query_include` に `1` を入れると、名前判定に引っかからない劇団も優先クエリに含めます
- `data/output/venue_master.csv` の `query_include` に `1` を入れると、名前判定や除外語に引っかかる劇場も優先クエリに含めます

ローカルで公開用 JSON の commit と push まで含めたい場合:

1. `.venv/Scripts/python.exe src/run_pipeline.py --publish`

補足:

- `--publish` は `docs/data/schedule_list.json` と `docs/data/master_data.json` に差分がある時だけ commit と push を行います
- 通常の GitHub Actions 運用では不要です。`main` に公開データのコミットを増やしたい時だけ使ってください
- コミット文言を固定したい場合は `--commit-message "Update published schedule data"` を付けられます

## GitHub Actions で自動実行する

このリポジトリには GitHub Actions 用 workflow を追加できます。API 版 collector を使って定期実行し、`docs/` を GitHub Pages へ直接デプロイする想定です。`main` への自動 commit / push は行いません。

必要な Secrets / Variables:

- `X_BEARER_TOKEN`: X recent search API 用 Bearer Token
- `GH_MODELS_TOKEN`: GitHub Models 抽出用トークン
- `GH_MODELS_MODEL` (optional): 既定モデルを上書きしたい場合の repository variable
- `GH_MODELS_API_VERSION` (optional): API version を上書きしたい場合の repository variable

補足:

- workflow は repository secret `GH_MODELS_TOKEN` を使い、実行時に `GH_MODELS_TOKEN` と `GITHUB_TOKEN` の両方へ渡します
- ローカル実行では従来どおり `.env` の `GITHUB_TOKEN` だけでも動作します

workflow の内容:

- `src/build_priority_queries_from_masters.py` でクエリ設定を再生成
- `src/run_pipeline.py` を実行
- workflow 実行中に `docs/data/schedule_list.json` と `docs/data/master_data.json` を更新し、`docs/` 全体を GitHub Pages にデプロイ
- `data/output/organization_master.csv` と `data/output/venue_master.csv` を含む `main` への push でも自動実行

追加後は GitHub の Actions タブから手動実行でき、schedule と対象ファイルの push でも自動実行されます。

## GitHub Pages で公開する

GitHub Pages 用の公開ファイルは `docs/` に出力します。Actions が workflow 実行時に `docs/` をそのまま Pages へデプロイします。

1. `.venv/Scripts/python.exe src/build_schedule_list.py` を実行する
2. `docs/data/schedule_list.json` が更新されることを確認する
3. GitHub に push する
4. GitHub の Settings > Pages で Source を `GitHub Actions` に設定する

公開後の構成:

- `docs/index.html` がトップページになります
- `docs/app.js` と `docs/styles.css` が画面を構成します
- `docs/data/schedule_list.json` が公開データです

注意:

- `docs/data/schedule_list.json` は公開ファイルなので、載せたデータは誰でも見られます
- X 収集や GitHub Models 抽出は GitHub Pages 上では動かず、Actions かローカルで生成した `docs/` を配備する運用です

## 出力

- CSV は `data/output/` に保存されます
- 重要クエリ一覧は `config/priority_queries.json` です
- 公開用 JSON はローカル実行時は `docs/data/` に保存され、Actions では同じ内容を Pages へ配備します
- 劇団・劇場マスターは `data/output/organization_master.csv` と `data/output/venue_master.csv` を参照します