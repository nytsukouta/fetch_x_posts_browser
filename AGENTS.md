# AGENTS.md

## プロジェクト概要

このリポジトリは、X 上の石川県を中心とした演劇・舞台情報を収集し、GitHub Models で構造化・イベント統合したうえで、公開スケジュールと X 投稿候補を生成するシステムです。

詳細な利用手順と運用方法は `README.md`、データモデルは `docs/ONTOLOGY.md`、公開 JSON の仕様は `web/SCHEMA.md` を参照してください。

## 基本方針

- 変更前に関連するコード、テスト、README・設計文書を確認する。
- 既存の公開 API、CSV/JSON のフィールド名、文字コード、CLI オプションを変更しない。
- 小さく局所的に変更し、無関係な整形や大量のリネームを行わない。
- 推測でデータを補完せず、原投稿の情報・マスター・手動補正を区別する。
- 投稿者アカウントと主催団体を同一視しない。
- 新しい判定ルールを追加する場合は、既存の共通ルールとの重複や矛盾を確認する。

## ディレクトリと責務

- `src/run_pipeline.py`: 収集から公開データ生成までの一括実行入口
- `src/build_priority_queries_from_masters.py`: 団体・会場マスターから優先検索クエリを生成
- `src/fetch_x_posts.py`: X Recent Search API による収集
- `src/extract_events_github_models.py`: X 投稿、引用投稿、添付画像からの構造化抽出
- `src/event_candidate_rules.py`: schedule 掲載と X 投稿候補に共通する公開判定
- `src/event_cumulative_core.py`: イベント統合・正規化の純粋ロジック
- `src/build_event_cumulative.py`: 累積観測からイベント単位 CSV を生成
- `src/build_schedule_list.py`: 公開用 schedule CSV/JSON を生成
- `src/manual_event_overrides.py`: 公演単位の手動補正の検証・適用
- `src/maintenance_server.py`: ローカル専用の保守 API と画面のサーバー
- `web/`: 一般公開用の静的 Web
- `maintenance_web/`: ローカル専用の保守画面
- `docs/`: GitHub Pages 配信用の生成物
- `config/`: 優先クエリ、イベント別名、手動補正などの設定
- `data/output/`: 中間生成物・累積データ・公開用内部データ
- `tests/`: Python の単体テスト

## データ編集ルール

- `data/output/structured_events*.csv`、`data/output/event_cumulative*.csv`、`data/output/schedule_list.*`、`docs/data/*.json` を通常は直接編集しない。
- 団体情報は `data/output/organization_master.csv`、会場情報は `data/output/venue_master.csv` を編集する。
- 公演単位の補正は `config/manual_event_overrides.json` を使用する。
- 同一イベントの手動統合は `config/event_aliases.csv` の `canonical_event_id,alias_event_id` を使用する。
- Web の HTML/CSS/JavaScript を変更するときは `web/` 側を編集し、必要に応じて `src/sync_web_to_docs.py` で `docs/` を同期する。
- 生成済みデータを変更した場合は、再生成手順と差分の妥当性を確認する。

## 実行と検証

- Windows の通常実行では `.venv/Scripts/python.exe` を優先する。
- 変更後は可能な範囲で `pytest tests/ -q` を実行する。
- 収集を行わず既存 CSV で確認する場合は `src/run_pipeline.py --skip-collect --input-csv ...` を使用する。
- tracked ファイルを汚さず確認する場合は `--local-preview-dir` を使用する。
- 公開 JSON を直接編集せず、生成元を修正して再生成する。
- テストやローカル確認で API 呼び出しが発生する場合は、入力件数や `--extract-limit` を制限する。

## 危険な操作

ユーザーから明示的に依頼されない限り、次の操作を実行しない。

- `--publish` による commit / push
- X への live 投稿（`--post-new-events` を dry-run なしで実行すること）
- 大量の X API 収集や GitHub Models 呼び出し
- 累積 CSV、seed CSV、投稿済み記録の削除
- `.env`、API トークン、GitHub Secrets などの認証情報の表示・コミット
- `main` への force push、履歴の書き換え、無関係なファイルの一括変更

X 投稿候補の確認には、まず `--post-dry-run` または `src/post_new_events_to_x.py --dry-run` を使用してください。

## パイプライン上の注意

- X 投稿の重複排除は `tweet_url` または `tweet_id` を基準にする。
- 累積データに既に存在する投稿を再抽出しない。
- `structured_events_cumulative.csv` をイベント統合の基礎データとして扱う。
- schedule と X 投稿候補の公開条件は `src/event_candidate_rules.py` の共通ロジックを利用する。
- `event_cumulative_base.csv` は手動補正前、`event_cumulative.csv` は手動補正後のデータである。
- 手動補正を解除・変更する場合も、補正前の値を壊さない。
- `data/bootstrap/structured_events_cumulative_seed.csv` は GitHub Actions の cold start 対策用の基準データである。
- GitHub Actions の定期実行は X live 投稿、push 起動は投稿なし、手動実行は `post_mode` に従う。

## 実装上の規約

- Python は既存の型注釈と `from __future__ import annotations` の使用方針に合わせる。
- ファイル書き込みは既存の `atomic_io` の仕組みを優先する。
- CSV は既存の UTF-8 with BOM と `csv.DictReader` / `csv.DictWriter` の形式を維持する。
- パスは `src/` からリポジトリルートを解決する既存方式に合わせる。
- 外部 API のエラー、欠損データ、空 CSV、古い artifact を考慮する。
- 既存テストを変更する場合は、仕様変更を反映する必要性を確認し、実装に合わせるだけの変更は避ける。

## 変更完了時の報告

最終報告には次を簡潔に含める。

1. 変更したファイルと目的
2. 実行したテスト・検証コマンド
3. 未実行の検証、環境依存事項、注意点
