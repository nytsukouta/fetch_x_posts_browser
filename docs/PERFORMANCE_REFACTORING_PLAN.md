# パイプライン性能・信頼性改善計画

## 1. 目的

この文書は、現在の公開仕様を壊さずに、次の問題を段階的に改善するための実装計画である。

- 同一入力に対する GitHub Models の再呼び出し
- X API、GitHub Models、X投稿処理が途中で失敗した際の再処理漏れ
- GitHub Actions における不要なフルパイプライン実行
- CSV、JSON、Git、GitHub CLI の重複処理
- イベント数増加時に悪化する二乗比較
- Python・JavaScript内に分散した同種処理

この計画は別の実装担当者またはAIモデルが、各フェーズを独立した変更として実装できる粒度で記載する。

## 2. 現状の前提

2026年7月時点のデータ規模は、おおむね次のとおりである。

- X検索クエリ: 約54件
- 構造化累積: 約430行
- ノイズ除去後累積: 約284行
- イベント累積: 約92行
- 公開スケジュール: 約50行

現規模ではCSVの読み書きやブラウザ描画の絶対時間はまだ小さい。最初に最適化すべき対象は、外部APIの無駄な再呼び出しと、途中失敗時の不整合である。

## 3. 変更時の不変条件

全フェーズで次を守ること。

1. 既存の公開JSON、CSV、CLIオプションのフィールドを削除・改名しない。
2. CSVは既存どおりUTF-8 with BOMで読み書きする。
3. `tweet_url`、なければ`tweet_id`を投稿の同一性として扱う。
4. `structured_events_cumulative.csv`を観測データの基礎とする。
5. `event_cumulative_base.csv`は手動補正前、`event_cumulative.csv`は補正後として維持する。
6. schedule掲載とX投稿候補は`src/event_candidate_rules.py`の共通条件を使う。
7. 投稿者アカウントを主催団体として自動補完しない。
8. `web/`を静的Webの編集元とし、`docs/`は`src/sync_web_to_docs.py`で同期する。
9. live投稿、`--publish`、外部APIの大量呼び出しを検証目的で実行しない。
10. 最適化前後でイベント統合結果が変わる変更は、明示したフェーズ以外では行わない。

## 4. 実装順序

以下の順に、原則として1フェーズ1PRで実装する。

| フェーズ | 内容 | 効果 | リスク |
|---|---|---:|---:|
| 0 | ベースラインと回帰テスト | 後続変更の安全性確保 | 低 |
| 1 | 小さく明確な重複処理の解消 | I/O削減、決定性向上 | 低 |
| 2 | X投稿ログの逐次チェックポイント | 重複投稿防止 | 中 |
| 3 | 収集・抽出失敗キュー | 投稿取りこぼし防止 | 中〜高 |
| 4 | LLM二次統合キャッシュ | API時間・料金削減 | 高 |
| 5 | GitHub Actionsの責務分離 | 不要なAPI実行削減 | 中 |
| 6 | 保守画面・Webの軽量化 | 操作応答改善 | 低〜中 |
| 7 | イベント比較の候補索引化 | 将来のスケーラビリティ | 高 |
| 8 | 共通処理の整理 | 保守性向上 | 中 |

フェーズ7と8は現在の規模では急がない。フェーズ0〜5を優先する。

---

## 5. フェーズ0: ベースラインと回帰テスト

### 5.1 目的

性能改善によって公開件数、イベントID、統合結果、投稿候補が意図せず変わらないことを検証できる状態にする。

### 5.2 追加するテスト

#### `tests/test_pipeline_regression.py`（新規）

外部APIを呼ばず、小さなfixture CSVから次を確認する。

- 同じ入力を2回処理しても累積投稿数が増えない。
- `tweet_url`が同じ投稿は1件になる。
- 新規投稿がない場合に既存累積CSVを利用できる。
- `event_cumulative_base.csv`へ手動補正値が混入しない。
- `event_cumulative.csv`には手動補正が適用される。

#### `tests/test_event_cumulative_golden.py`（新規）

LLMをモックし、固定した入力レコードについて次を保存・比較する。

- `event_id`
- `event_key`
- `source_tweet_urls`
- `source_tweet_count`
- イベント件数

JSONまたはインライン辞書を期待値にする。実データ全体をfixtureへコピーしない。

#### 既存テストの拡張

- `tests/test_post_new_events_text.py`: 投稿途中失敗とログ保存を追加する。
- `tests/test_fetch_x_posts_state.py`: 部分失敗時のstate更新を追加する。
- `tests/test_maintenance_server.py`: キャッシュ導入後の無効化を追加する。

### 5.3 計測ログ

`src/run_pipeline.py`の各工程を計測できるよう、標準ライブラリの`time.perf_counter()`を使った小さなヘルパーを追加してもよい。

候補:

```text
timed_step(label: str, action: Callable[[], T]) -> T
```

出力例:

```text
timing: collect_posts=12.43s
timing: extract_events=31.08s
timing: build_event_cumulative=4.21s
```

外部監視サービスや新規依存パッケージは導入しない。

### 5.4 完了条件

- `pytest tests/ -q`が成功する。
- 外部APIなしで回帰テストを実行できる。
- 後続フェーズでイベント統合結果の差を検出できる。

---

## 6. フェーズ1: 小さく明確な重複処理の解消

### 6.1 schedule JSONを一度だけ構築する

対象: `src/build_schedule_list.py`

現状は同じ`rows`に対して`write_json()`を2回呼び、内部用とPages用のpayloadを別々に構築している。このため全件変換とJSONシリアライズが重複し、秒境界をまたぐと`generated_at`だけが異なる可能性がある。

次のように分割する。

```text
build_json_payload(rows: list[dict[str, Any]], generated_at: str | None = None) -> dict[str, Any]
serialize_json_payload(payload: dict[str, Any]) -> str
write_json_text(output_path: Path, text: str) -> None
```

`main()`ではpayloadとJSON文字列を一度だけ生成し、`args.output_json`と`args.pages_json`へ同じ文字列をatomic writeする。

`rebuild_maintained_outputs.py`から使用している既存の`write_json(rows, path)`は互換ラッパーとして残してよい。公開関数を削除しない。

テスト:

- 2つの出力ファイルがバイト単位で一致する。
- `generated_at`が一致する。
- `prefecture`付与と既存スキーマが維持される。

### 6.2 Actions内の検索クエリ二重生成を解消する

対象:

- `.github/workflows/daily-pipeline.yml`
- `src/run_pipeline.py`

推奨変更は、ワークフロー側の`Rebuild query configuration`ステップを削除し、`run_pipeline.py`側へ一本化することである。ローカル実行時の自動生成は維持する。

この変更では新しいCLIオプションを増やさない。

テスト・確認:

- `run_pipeline.py --skip-collect`でもクエリJSONが生成される既存挙動を維持する。
- workflow内に`build_priority_queries_from_masters.py`の直接実行が残っていないことを確認する。

### 6.3 ローカルartifact同期の同一run省略

対象: `src/github_artifact_sync.py`

`sync_latest_artifact()`で最新成功runを取得した後、`data/output/_tmp/maintenance_sync_state.json`の`run_id`と一致し、必要ファイルがすべて存在する場合はダウンロードを省略できるようにする。

追加引数:

```text
sync_latest_artifact(..., force: bool = False) -> dict[str, Any]
```

省略時の戻り値へ`skipped: true`を追加する。既存キーは維持する。保守画面の「最新データ取得」を明示的な再取得として扱いたい場合は、APIから`force=true`を渡すか、UIに「強制再取得」を追加する。初期実装では既存ボタンを`force=False`としてよい。

### 6.4 完了条件

- JSONの内容が従来と同じである。
- workflowで検索設定が1回だけ生成される。
- 同一artifact runの再同期時に`gh run download`が呼ばれない。

---

## 7. フェーズ2: X投稿ログの逐次チェックポイント

### 7.1 問題

`src/post_new_events_to_x.py`は全候補処理後に`posted_events.csv`を一括更新する。途中で通常のAPIエラーが発生すると、すでに成功した投稿もログへ残らず、次回に再投稿される可能性がある。

### 7.2 実装内容

対象: `src/post_new_events_to_x.py`

#### ログ行生成を関数化する

```text
build_post_log_row(row: dict[str, str], posted_tweet_id: str) -> dict[str, str]
```

#### append方式をatomic置換へ変更する

既存`append_post_log()`の外部シグネチャは維持しつつ、内部では次を行う。

1. 既存CSVを`load_csv_rows()`で読む。
2. `event_id`をキーに辞書化する。
3. 新しい行で同じ`event_id`を上書きする。
4. 既存フィールド順を維持して`atomic_open()`で全体を書き直す。

これによりプロセス停止時のCSV途中書き込みを防ぐ。既存ログに同一`event_id`が重複している場合は、最後の行を採用する。

#### 投稿ループ内で即時保存する

各候補について以下の順にする。

1. `post_tweet()`を実行する。
2. 成功時は取得したtweet IDを含む1行を即時保存する。
3. `DuplicateTweetContentError`時も、従来どおり空の`posted_tweet_id`で即時保存する。
4. その他の例外時はログへ成功扱いで保存せず、例外を再送出する。

既存CSVスキーマは変更しない。`status`列は追加しない。空の`posted_tweet_id`は既存どおりduplicate-contentとして扱う。

### 7.3 テスト

`tests/test_post_new_events_text.py`または新しい`tests/test_post_new_events_logging.py`へ追加する。

- 1件目成功、2件目例外の場合、1件目だけがログに残る。
- duplicate-contentもログに残る。
- 同じ`event_id`を再保存しても行数が増えない。
- atomic write後もUTF-8 BOMとヘッダーが維持される。
- dry-runではログが変更されない。

### 7.4 完了条件

- 投稿成功直後にログへ記録される。
- 途中失敗後の再実行で、成功済みイベントが候補にならない。
- live APIを使わずモックで全テストが通る。

---

## 8. フェーズ3: 収集・抽出失敗キュー

### 8.1 方針

`since_id`は「Xから取得済み」の位置として維持し、抽出成否とは分離する。取得済みだが未抽出の投稿を永続キューへ保存し、次回以降に再試行する。

収集stateを抽出完了時まで戻す方式は採用しない。複数クエリの`since_id`を巻き戻すと大量再取得になりやすいためである。

### 8.2 新しいファイル

`data/output/_state/extraction_pending.csv`

- 収集CSVと同じ列を保持する。
- `tweet_url`、なければ`tweet_id`で一意にする。
- tracked対象にはしない。
- Actions cacheと耐久artifactへ含める。

`data/output/_state/extraction_failures.csv`

列:

```text
tweet_id,tweet_url,attempt_count,last_error,last_attempted_at
```

エラーメッセージは認証トークンやHTTP Authorizationヘッダーを含めない。長すぎるメッセージは例えば1000文字で切る。

### 8.3 `src/run_pipeline.py`の変更

追加定数:

```text
DEFAULT_PENDING_QUEUE_CSV
DEFAULT_EXTRACTION_FAILURES_CSV
```

追加関数候補:

```text
merge_pending_queue(new_rows, queued_rows, fieldnames) -> list[dict[str, str]]
write_pending_queue(rows, fieldnames) -> None
remove_successful_pending_rows(successful_keys: set[str]) -> None
```

処理順を次のように変更する。

1. X収集結果または`--input-csv`を読む。
2. 入力内重複と累積済み投稿を除外する。
3. 残った投稿を既存pending queueとマージしてatomic保存する。
4. pending queueを`extract_events_github_models.py`へ渡す。
5. 抽出成功した投稿だけ累積CSVへマージする。
6. 累積へ保存できた投稿だけpending queueから削除する。
7. 失敗投稿はqueueに残す。

### 8.4 `src/extract_events_github_models.py`の変更

抽出結果と失敗情報を呼び出し元が識別できる必要がある。

互換性を保つため、既存CSV出力に加えて任意の失敗CSV引数を追加する。

```text
--failures-output-csv data/output/_state/extraction_failures_current.csv
```

各Futureの結果を次のいずれかで保持する。

```text
ExtractionResult(row=..., event=..., error=None)
ExtractionResult(row=..., event=None, error="...")
```

dataclassを使ってよい。例外を標準エラーへ出すだけで終わらせず、失敗CSVへ書く。プロセス自体は成功行が1件以上あっても、失敗件数を出力する。

終了コード方針:

- 全件成功: `0`
- 一部失敗: `2`
- 入力・認証・出力など全体エラー: `1`

ただし`run_pipeline.py`は終了コード`2`を認識し、成功出力を累積へ取り込んだ後、失敗投稿をqueueに残してパイプラインを非成功で終了させる。これによりActionsの失敗通知と再試行が働く。

### 8.5 X lookupのまとめ取得

失敗キューが安定した後、古いCSVで引用・画像列が欠ける場合のX lookupを複数ID単位へまとめる。

実装案:

```text
fetch_tweet_contexts(bearer_token: str, tweet_ids: list[str]) -> dict[str, dict[str, str]]
```

- X APIが許容するID上限でチャンク化する。
- 既存`fetch_tweet_context()`は1件用互換ラッパーとして残す。
- lookup済み結果を同一run内で`tweet_id`キャッシュする。
- X APIの仕様を実装時に公式ドキュメントで再確認する。

### 8.6 Actions変更

cacheと`pipeline_history_snapshot.zip`へ以下を追加する。

```text
data/output/_state/extraction_pending.csv
data/output/_state/extraction_failures.csv
```

artifact復元の許可ファイルと必須・任意ファイル定義も更新する。古いartifactに新規ファイルがなくても復元できるよう、新規2ファイルは任意とする。

### 8.7 テスト

- 一部抽出失敗時、成功投稿だけ累積へ入り、失敗投稿はqueueに残る。
- 次回実行時、収集結果に含まれなくてもqueueから再試行される。
- 再試行成功後にqueueから削除される。
- 同じ投稿が収集CSVとqueueにあっても1回だけ抽出される。
- 累積済み投稿はqueueから除去される。
- 古いartifactにqueueがなくても復元できる。

### 8.8 完了条件

- GitHub Modelsの一時障害で投稿が永久に失われない。
- pending queueがActions run間で引き継がれる。
- 全処理が`tweet_url`または`tweet_id`で冪等になる。

---

## 9. フェーズ4: LLM二次統合キャッシュ

### 9.1 対象

- `src/event_cumulative_llm.py`
- `src/build_event_cumulative.py`
- `.github/workflows/daily-pipeline.yml`
- `src/github_artifact_sync.py`

### 9.2 キャッシュ形式

新規ファイル:

```text
data/output/_state/event_dedupe_cache.json
```

形式:

```json
{
  "version": 1,
  "entries": {
    "sha256...": {
      "model": "openai/gpt-5",
      "api_version": "2026-03-10",
      "decision": {"decisions": []},
      "created_at": "2026-07-17T12:34:56+09:00"
    }
  }
}
```

キャッシュキーは次の値をUTF-8 JSONへ正規化し、SHA-256で生成する。

```text
cache_key = sha256({
  cache_schema_version,
  model,
  api_version,
  system_prompt,
  cluster_records
})
```

`cluster_records`は`build_dedupe_prompt()`へ渡すものと同じ項目を使い、JSONキーをソートする。入力順でキーが変わらないよう、レコードを次の安定キーで並べる。

```text
(event_key, event_name, organization, normalized_venue_name, start_date, end_date, start_time)
```

`source_text`を含める。抽出根拠が変わった場合は再判定が必要なためである。

### 9.3 実装API

`src/event_cumulative_llm.py`へ追加する。

```text
load_dedupe_cache(path: Path) -> dict[str, Any]
write_dedupe_cache(path: Path, payload: dict[str, Any]) -> None
build_dedupe_cache_key(cluster, model, api_version) -> str
secondary_dedupe(records, model, cache_path: Path | None = DEFAULT_CACHE_PATH) -> list[dict[str, Any]]
```

既存呼び出しとの互換性のため、`cache_path`は既定値付きとする。

処理:

1. クラスターごとにcache keyを作る。
2. entryがあればAPIを呼ばずdecisionを利用する。
3. entryがなければAPIを呼ぶ。
4. 応答を既存ロジックで検証する。
5. 有効なdecisionだけキャッシュへ追加する。
6. 全クラスター終了後に一度だけatomic writeする。

APIエラー、JSON不正、全IDを網羅しないdecisionはキャッシュしない。

### 9.4 decision検証を強化する

追加関数:

```text
validate_dedupe_decisions(payload, valid_ids: set[str]) -> list[dict[str, Any]] | None
```

条件:

- `decisions`が配列である。
- 各`member_ids`が配列である。
- 未知IDを含まない。
- 同じIDを複数decisionに含めない。
- 全IDがちょうど1回含まれる。
- `canonical_name`は文字列である。

不正応答は従来どおりそのクラスターを統合せず、キャッシュしない。

### 9.5 キャッシュの永続化

Actions cacheと耐久artifactへ`event_dedupe_cache.json`を追加する。古いartifactでは任意ファイルとして扱う。

キャッシュは生成物であり、Gitへcommitしない。

### 9.6 テスト

- 初回はモックAPIが1回呼ばれ、キャッシュが保存される。
- 同一入力の2回目はAPIが呼ばれない。
- モデル、APIバージョン、system prompt、source textのいずれかが変わると再呼び出しされる。
- レコード順が変わっても同じキーになる。
- 不正decisionは保存されない。
- 壊れたキャッシュJSONは警告後に空キャッシュとして扱う。
- キャッシュ利用時と非利用時で統合結果が一致する。

### 9.7 完了条件

- 同一入力・同一設定の再実行で二次統合API呼び出しが0件になる。
- キャッシュ削除時は従来どおり再判定できる。
- キャッシュがなくてもパイプラインが動く。

---

## 10. フェーズ5: GitHub Actionsの責務分離

### 10.1 目標

変更内容に応じて次の3モードを使い分ける。

| モード | 収集 | 抽出 | 累積統合 | schedule生成 | Pages配備 |
|---|---:|---:|---:|---:|---:|
| full | する | する | する | する | する |
| rebuild | しない | しない | する | する | する |
| pages | しない | しない | しない | 必要ならしない | する |

### 10.2 推奨構成

最初はworkflowファイルを増やさず、`.github/workflows/daily-pipeline.yml`内に変更判定ジョブを追加する。

`dorny/paths-filter`などの外部Actionは増やさず、`git diff --name-only`またはイベント情報からシェルで判定する。schedule実行は常に`full`、手動実行は入力で選択、pushは変更パスから決定する。

手動入力を追加する。

```yaml
pipeline_mode:
  type: choice
  options: [auto, full, rebuild, pages]
  default: auto
```

### 10.3 モード判定

#### `full`

- `schedule`
- 手動`pipeline_mode=full`
- 次の変更を含むpush:
  - `src/fetch_x_posts.py`
  - `src/extract_events_github_models.py`
  - `src/x_tweet_context.py`
  - `src/github_models_client.py`
  - `src/build_priority_queries_from_masters.py`
  - `data/output/organization_master.csv`
  - `data/output/venue_master.csv`

#### `rebuild`

- 手動`pipeline_mode=rebuild`
- 次の変更のみを含むpush:
  - `config/manual_event_overrides.json`
  - `config/event_aliases.csv`
  - `src/event_candidate_rules.py`
  - `src/event_cumulative_core.py`
  - `src/event_cumulative_llm.py`
  - `src/build_event_cumulative.py`
  - `src/build_schedule_list.py`
  - `src/manual_event_overrides.py`

#### `pages`

- 手動`pipeline_mode=pages`
- `web/**`、`src/sync_web_to_docs.py`、静的ドキュメントだけのpush

分類不能な`src/**`変更は安全側に倒して`full`とする。

### 10.4 `run_pipeline.py`のCLI追加

```text
--skip-query-rebuild
--rebuild-only
```

`--rebuild-only`の仕様:

- X収集を行わない。
- GitHub Modelsによる投稿抽出を行わない。
- 復元済み`structured_events_filtered_cumulative.csv`からイベント統合を再実行する。
- scheduleとmaster JSONを再生成する。
- `--post-new-events`とは併用不可。

ただしフェーズ1でクエリ生成をパイプラインへ一本化しているため、`--skip-query-rebuild`はworkflowが明示的に事前生成する場合だけ必要である。不要なら追加しない。

### 10.5 workflowの処理

- `full`: 現行パイプラインを実行する。
- `rebuild`: artifact復元後、`run_pipeline.py --rebuild-only`を実行する。
- `pages`: テスト、`sync_web_to_docs.py`、Pages artifact生成だけを行う。X/GitHub Models secretsの検証をしない。
- live X投稿は`full`かつ既存`post_mode=live`の場合だけ許可する。
- `pages`と`rebuild`ではX投稿を常に無効化する。

### 10.6 注意

`web/app.js`は`../data/output/schedule_list.json`を参照し、`docs/app.js`は同期時にPages用パスへ変換される既存仕様を確認すること。pages-only配備で既存`docs/data/*.json`がcheckout時に存在する前提が崩れる場合は、最新Pages用JSONをartifactから復元する処理を追加する。

### 10.7 テスト・検証

- workflowのモード判定を独立したPythonまたはPowerShellスクリプトにする場合、その純粋関数を単体テストする。
- webのみ変更ではX・GitHub Modelsのsecrets検証とAPIパイプラインが実行されない。
-手動補正のみ変更では収集・抽出が実行されない。
- schedule起動では従来どおりfullとlive投稿が選ばれる。
- push起動では従来どおりlive投稿しない。
- Pages artifactに`docs/data/schedule_list.json`と`docs/data/master_data.json`が含まれる。

### 10.8 完了条件

- Webだけの変更で外部API呼び出しが0件になる。
- 手動補正だけの変更でX収集と投稿抽出が0件になる。
- 定期実行の挙動は従来と同じである。

---

## 11. フェーズ6: 保守画面とWebの軽量化

### 11.1 保守サーバーのスナップショットキャッシュ

対象: `src/maintenance_server.py`

`MaintenanceService`に次を追加する。

```text
self._snapshot_cache: dict[Path, tuple[int, int, Any]]
self._status_cache: tuple[float, dict[str, Any]] | None
```

ファイルキャッシュキーには`st_mtime_ns`と`st_size`を使う。対象:

- `event_cumulative_base.csv`
- `event_cumulative.csv`
- `schedule_list.json`
- `manual_event_overrides.json`

追加ヘルパー候補:

```text
_load_cached_csv(path: Path) -> list[dict[str, str]]
_load_cached_json(path: Path, default: Any) -> Any
_invalidate_paths(*paths: Path) -> None
```

補正保存、削除、再構築、artifact同期後に対象キャッシュを明示的に破棄する。外部エディタでファイルが変わった場合はmtimeで自動更新する。

`git_status()`と`gh_status()`は5秒程度のTTLキャッシュにする。補正publish直後はGitキャッシュを破棄する。

### 11.2 保守画面の重複取得を削減する

対象: `maintenance_web/maintenance.js`

一覧レスポンスにすでに`base`、`effective`、`override`、`schedule`が含まれるため、一覧から選択した直後の詳細API再取得を省略できる。保存後やrevision不一致時だけ詳細を再取得する。

ただし一覧payloadが将来大きくなる場合に備え、先にサーバーキャッシュだけ導入し、その後ネットワーク計測を見て実施してもよい。

### 11.3 Web検索のdebounceと事前計算

対象:

- `web/app.js`
- `web/masters.js`
- `maintenance_web/maintenance.js`

追加関数:

```text
debounce(callback, delayMs)
```

検索入力のみ150msでdebounceする。select変更、クリアボタン、URLからの初期復元は即時反映する。

公開schedule読込時に各itemへ非公開の派生値を作るか、`WeakMap`へ保持する。

```text
searchText
prefecture
startDate
endDate
```

元の公開JSONオブジェクトを変更しない方針なら`Map(event_id -> derived)`を使う。

`applyFilters()`では`totalScope`と表示対象を別々に全走査せず、1回のループで両方を数える。

### 11.4 カレンダー更新

最初はFullCalendarの全件差分アルゴリズムを独自実装しない。debounceと事前計算だけ実装し、必要なら`batchRendering()`内でremove/addする。イベント数が数百件を超えてからID差分更新を検討する。

### 11.5 同期とテスト

- `web/`変更後に`src/sync_web_to_docs.py`を実行する。
- `tests/test_sync_web_to_docs.py`を実行する。
- 検索、地域、upcoming、URLの`event`・`loc`・`q`パラメーターを手動確認する。
- 保守画面で保存後に一覧・詳細・件数が即時更新されることを確認する。

---

## 12. フェーズ7: イベント比較の候補索引化

このフェーズはイベント統合結果を変えるリスクが高い。現在のデータ規模では、フェーズ4まで完了しても速度が不足する場合に実施する。

### 12.1 対象関数

`src/event_cumulative_core.py`:

- `build_similarity_clusters()`
- `attach_event_updates()`
- `merge_placeholder_records()`
- `suppress_preview_like_records()`

`src/build_schedule_list.py`:

- `build_schedule_rows()`
- `schedule_rows_look_same()`
- `suppress_preview_like_duplicates()`

### 12.2 実装方針

比較条件自体は変えず、比較候補の探索だけを狭める。

事前計算する値:

```text
compact_event_name
compact_organization
normalized_venue_group_key
start_date_object
end_date_object
year_month_bucket
```

候補インデックス例:

```text
by_organization_month[(organization_key, yyyy_mm)]
by_venue_month[(venue_key, yyyy_mm)]
by_start_date[(start_date, category)]
```

日付範囲が月をまたぐ場合は、含まれる各月へ登録する。日付不明レコードは従来どおり別のfallback群で比較し、候補から脱落させない。

### 12.3 類似クラスター

`build_similarity_clusters()`は比較済みペアを`set[tuple[int, int]]`へ記録し、同じ`SequenceMatcher`比較を繰り返さない。必要ならunion-findで連結成分を作る。

重要: 現行アルゴリズムが推移的類似をどこまで認めているかをgolden testで固定してから変更する。

### 12.4 schedule側の重複排除

まず次の粗いキーで候補を絞る。

```text
(category, start_date, end_date)
```

そのバケット内だけ`texts_are_compatible()`を実行する。日付が完全一致しない既存例がある場合は、現行条件を確認し、同じ候補集合になる別キーを設計する。

イベント累積側とschedule側のpreview抑止は、このフェーズでは無理に統合しない。先に性能変更だけを行い、出力件数が完全一致することを確認する。

### 12.5 ベンチマーク

テスト専用に、実データをコピーせず合成イベントを生成する。

- 100件
- 1,000件
- 同一団体・同一月へ集中した最悪ケース

絶対秒数をCIの厳密な合否条件にしない。比較回数をカウンターで検証し、候補索引化後に大幅に減ることを確認する。

### 12.6 完了条件

- golden testでイベント統合結果が完全一致する。
- schedule JSONのitemsが完全一致する。`generated_at`は比較対象外とする。
- 最悪ケースの文字列類似度比較回数が二乗全探索より減る。

---

## 13. フェーズ8: 共通処理の整理

性能改善と同時に大規模共通化を行わない。各フェーズ完了後、テストが十分になってから実施する。

### 13.1 共通化候補

#### `src/text_normalization.py`

- `compact_text()`
- Unicode正規化
- タイトル比較用の共通前処理

#### `src/x_identity.py`

- `normalize_handle()`
- `tweet_identity_key()`
- X URLからのユーザー名・tweet ID抽出

#### `src/llm_response.py`

- GitHub Modelsレスポンスからtext contentを取り出す処理
- JSON objectへの変換

#### `src/event_preview_rules.py`

- preview/placeholder判定の共通部分

### 13.2 共通化前の必須作業

同名・類似関数が現在まったく同じ仕様とは限らない。次を表にしてから移動する。

- 空文字の扱い
- URL形式・`@handle`形式の扱い
- Unicode・大文字小文字の扱い
- 日付欠損時の扱い
- 月バケットの扱い
- 不正なLLMレスポンスの扱い

意図的な差は関数引数または別関数として残す。共通化を理由にデータ出力を変えない。

### 13.3 artifact復元処理

`.github/workflows/daily-pipeline.yml`のインラインPythonと`src/github_artifact_sync.py`で重複しているZIP検証・復元を共通化する。

推奨:

- ダウンロード層はActions APIと`gh` CLIで別のままにする。
- ZIPメンバー検証、CSVヘッダー検証、旧artifact互換、atomic copyだけを共通関数へする。
- ActionsはダウンロードしたZIPを共通CLIへ渡す。

候補CLI:

```text
python src/github_artifact_sync.py restore --snapshot <path> --root <path>
```

Actions側でも直接`extractall()`せず、一時ディレクトリで検証してから復元する。

---

## 14. 今回は実施しない変更

以下は規模に対して変更コストが大きいため、この計画の初期フェーズでは実施しない。

- CSV中心の内部状態を全面的にSQLiteへ移行すること
- X検索クエリの無条件な並列実行
- FullCalendarの独自仮想描画
- 公開JSON・CSVの破壊的スキーマ変更
- `event_id`生成方式の変更
- イベント統合ルールの閾値変更
- 新しい外部依存パッケージの導入

X APIの並列化はレート制限を悪化させる可能性がある。先に429・5xxの再試行、`Retry-After`対応、クエリ単位チェックポイントを実装する。

## 15. 全体の受け入れ条件

全フェーズを通した最終条件は次のとおり。

1. `pytest tests/ -q`が成功する。
2. 同じ入力から生成したイベント件数、`event_id`、schedule itemsが意図しない変更を起こさない。
3. 新規投稿がない再実行で、GitHub Models二次統合のAPI呼び出しが発生しない。
4. 投稿または抽出の途中失敗後も、成功済み状態と未処理状態が失われない。
5. WebだけのpushでX APIとGitHub Modelsを呼ばない。
6. 手動補正だけのpushでX収集と投稿抽出を行わない。
7. 定期Actionsでは従来どおり収集・抽出・公開・設定に応じたX投稿を行う。
8. `web/`と`docs/`の同期テストが成功する。
9. 新しいstate/cacheファイルがなくてもcold startできる。
10. 古いartifactを復元できる。

## 16. 各PRの報告テンプレート

各フェーズの実装完了時は、次を記録する。

```text
変更したファイル:
- ...

変更目的:
- ...

互換性:
- 既存CSV/JSON/CLIへの影響

実行したテスト:
- pytest ...

外部API呼び出し:
- なし / dry-runのみ / 実施内容

生成物差分:
- event件数
- schedule件数
- event_id差分

未実施・注意点:
- ...
```

## 17. 最初に着手する推奨タスク

別の実装担当者が最初に着手する場合は、フェーズ2の「X投稿ログの逐次チェックポイント」を推奨する。

理由:

- 変更範囲が`src/post_new_events_to_x.py`とテストに限定される。
- live APIを使わず完全にテストできる。
- イベント統合結果や公開JSONを変更しない。
- 途中失敗時の重複投稿という実害を直接防げる。

次にフェーズ1、フェーズ3、フェーズ4、フェーズ5の順で進める。