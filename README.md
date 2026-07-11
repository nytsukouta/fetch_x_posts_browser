# 北陸演劇情報収集

石川県の演劇関連投稿を、重要クエリだけで収集する最小構成です。

プロジェクトの概念、データの関係、イベント統合・公開判定の考え方は [docs/ONTOLOGY.md](docs/ONTOLOGY.md) を参照してください。

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
- 同じ tweet が複数クエリに引っかかった場合は、保存前に `tweet_url` / `tweet_id` 単位で重複除去します

## GitHub Models で構造化抽出

収集済み CSV から日時や場所などを抜き出すには、GitHub Models 版を使えます。

1. `.env` に `GH_MODELS_TOKEN` または `GITHUB_TOKEN` を設定する
2. 必要なら `GITHUB_MODELS_MODEL` を設定する
3. `.venv/Scripts/python.exe src/extract_events_github_models.py --limit 5` を実行する

画像入力を止めたい場合:

- `.venv/Scripts/python.exe src/extract_events_github_models.py --limit 5 --no-images`
- `src/run_pipeline.py` を使う場合も `--no-images` を付ける

出力先:

- `data/output/structured_events.csv`
- `data/output/structured_events_filtered.csv`

補足:

- `structured_events.*` は生の抽出結果です
- `structured_events_filtered.*` はノイズ除去後の結果です
- JSONL は通常運用では保存せず、必要な時だけ `--debug-outputs` を付けて保存します
- 既定では tweet の添付画像 URL があれば GitHub Models に画像入力として渡します。コストや入力サイズを抑えたい場合は `--no-images` を使ってください
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

## ローカルの公演メンテナンス画面

GitHub Actions が生成した最新の詳細データを取得し、公演名、団体、会場、日程、公式参照URL、公開状態を手動補正できます。管理画面は GitHub Pages へ配備されず、この端末の `127.0.0.1` だけで動作します。

前提:

- GitHub CLI (`gh`) をインストールして、このリポジトリを読めるアカウントで認証する
- 最新の `Daily Theater Pipeline` が成功し、`pipeline-history-main` artifact が残っている

起動:

1. Windowsでは `start_maintenance.bat` をダブルクリックする（または `.venv/Scripts/python.exe src/maintenance_server.py` を実行する）
2. 自動的に開く `http://127.0.0.1:8765/` を使用する
3. 「GitHubから最新データ取得」で最新artifactを同期する
4. 公演を編集して「補正を保存」する
5. ローカルプレビューを確認後、「補正をGitHubへ反映」する

ブラウザを自動で開かない場合は `--no-browser`、ポートを変える場合は `--port 8766` を指定します。

補正内容は `config/manual_event_overrides.json` にだけ永続保存されます。`data/output/event_cumulative.csv` や公開JSONを直接編集しないでください。補正前データは `data/output/event_cumulative_base.csv`、補正適用後データは `data/output/event_cumulative.csv` です。

「補正をGitHubへ反映」は、現在のブランチが `main` で、ローカルが `origin/main` より古くない場合に限り、補正JSONだけをcommit/pushします。他の変更はcommitへ含めません。条件を満たさない場合は自動pullやforce pushを行わず停止します。

トラブルシュート:

- `gh` が見つからない場合は GitHub CLI をインストールする
- 未認証の場合は端末で `gh auth login` を実行する
- artifact がない場合は GitHub Actions からパイプラインを一度成功させる
- orphan補正は元の `event_id` と元ツイートURLの両方で対象を見つけられない状態なので、補正内容を確認する

## docs/ への配信

`docs/` は GitHub Pages 配信用で、`web/` から生成します。HTML/CSS/JS を編集するときは `web/` 側だけを直接編集し、次のコマンドで `docs/` を再生成します。

1. `.venv/Scripts/python.exe src/sync_web_to_docs.py`

`docs/data/` 配下の公開 JSON は通常パイプライン（`run_pipeline.py`）が直接更新します。スキーマは [web/SCHEMA.md](web/SCHEMA.md) を参照してください。

## 一括実行

情報収集から構造化抽出、累積統合、スケジュール生成までを 1 コマンドで順番に実行できます。

1. `.venv/Scripts/python.exe src/run_pipeline.py`

既存の収集済みCSVから再実行したい場合:

1. `.venv/Scripts/python.exe src/run_pipeline.py --skip-collect --input-csv data/output/<収集済みCSV>.csv`

補足:

- 収集ステップは API 版のみで、`.env` の `X_BEARER_TOKEN` が必要です
- 抽出ステップでは `.env` の `GH_MODELS_TOKEN` または `GITHUB_TOKEN` が必要です
- 実行開始時に `src/build_priority_queries_from_masters.py` を自動実行し、最新のマスターから `config/priority_queries.json` を再生成します
- 抽出前に収集CSV内の重複 tweet を落とし、`data/output/structured_events_cumulative.csv` に既にある `tweet_url` / `tweet_id` は再抽出しません
- 同じ `tweet_url` は累積CSVに重複追加せず、新しい投稿だけを追加します
- 累積データは `data/output/structured_events_cumulative.csv` と `data/output/structured_events_filtered_cumulative.csv` に保存されます
- イベント単位の統合結果は `data/output/event_cumulative.csv` に保存されます
- `config/event_aliases.csv` に `canonical_event_id,alias_event_id` を書き足すと、別 event として分かれてしまった同一公演を `event_cumulative.csv` 段階で手動マージできます。canonical 側の `event_id` を残し、tweet 一覧や venue などは値のある側を優先して統合します
- 劇団マスターと劇場マスターはパイプラインでは自動更新せず、既存ファイルを参照します
- 最後にイベント単位データから `data/output/schedule_list.csv` と `docs/data/schedule_list.json` を更新します
- 抽出段階の JSONL は通常運用では保存せず、必要な時だけ `--debug-outputs` を付けて保存します

tracked な `config/` や `docs/` を汚さずにローカル確認したい場合:

1. `.venv/Scripts/python.exe src/run_pipeline.py --local-preview-dir`

補足:

- `--local-preview-dir` を付けると `config/priority_queries.json`、`docs/data/schedule_list.json`、`docs/data/master_data.json`、`web/data/master_data.json` を直接更新せず、既定では `data/output/_local_preview/` 配下へ保存します
- 別の保存先を使いたい場合は `--local-preview-dir data/output/my_preview` のように明示できます
- `--publish` とは同時に使えません

新しく見つかった公演の投稿文だけを確認したい場合:

1. `.venv/Scripts/python.exe src/post_new_events_to_x.py --dry-run --limit 3`

パイプライン実行に合わせて dry-run したい場合:

1. `.venv/Scripts/python.exe src/run_pipeline.py --skip-collect --input-csv data/output/<収集済みCSV>.csv --post-new-events --post-dry-run`

補足:

- 投稿対象は `data/output/event_cumulative.csv` のうち、投稿済み記録 `data/output/posted_events.csv` に存在しない upcoming 公演です
- X 投稿候補は schedule 掲載候補と同じ基準を使います。共通ゲートに加えて、劇場除外と演劇シグナル判定も通ったものだけを投稿します
- 投稿文面は公演内容を本文に書かず、公開中の schedule ページへ誘導する固定文言が既定です。URL に event_id ベースの差分を付けて、重複扱いを避けます
- 通常の dry-run では投稿済み記録を書き換えません
- 実投稿する場合は `--dry-run` を外し、`src/post_new_events_to_x.py` か `src/run_pipeline.py --post-new-events` を使います
- ローカル実行だけなら `.env` に `X_API_KEY`、`X_API_SECRET`、`X_ACCESS_TOKEN`、`X_ACCESS_TOKEN_SECRET` を入れれば十分です
- GitHub Actions から自動投稿する場合は、GitHub Secrets に同じ 4 つの値を追加してください
- Actions の定期実行では新規公演を live 投稿し、`push` 実行では投稿しません
- Actions の手動実行では `post_mode` に `off` / `dry-run` / `live` を指定できます
- Actions 側では `data/output/posted_events.csv` を cache で引き継ぎ、同じ公演の再投稿を防ぎます
- テスト投稿として明示したい場合は `--header "テスト投稿" --hashtag 石川演劇テスト` のように上書きできます
- 投稿先の schedule URL は `--site-url` または `.env` の `PUBLIC_SITE_URL` / `SITE_URL` で上書きできます。未指定時は git の origin から GitHub Pages URL を推定します

マスター運用メモ:

- `data/output/organization_master.csv` の `query_include` に `1` を入れると、名前判定に引っかからない劇団も優先クエリに含めます
- `data/output/venue_master.csv` の `query_include` に `1` を入れると、名前判定や除外語に引っかかる劇場も優先クエリに含めます
- どちらも `query_exclude` に `1` を入れると、マスターには残したまま優先クエリから除外します（X API 消費を抑えたい劇場・劇団に使用）

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