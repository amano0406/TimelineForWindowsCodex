# TimelineForWindowsCodex

`TimelineForWindowsCodex` は、Windows ローカルにある Codex Desktop 履歴を読み、スレッド単位の JSON 生成物として管理する CLI 専用ツールです。

English README: [README.md](README.md)

この製品の役割は、固定された master 出力先を最新化し、必要なときだけ ZIP として取り出せる状態にすることです。読みやすい全体タイムライン化や要約は後段の Timeline 製品や LLM に任せます。

## この README の役割

この README は、通常利用する人が「何をする製品か」「どう起動するか」「何が出力されるか」「どう確認するか」を最短で把握するための運用ガイドです。

設計判断、残タスク、方針メモは別文書に分けます。

- 進捗と残タスク: [TODO.md](TODO.md)
- settings 管理方針: [SETTINGS_POLICY.md](SETTINGS_POLICY.md)
- Docker 優先方針: [DOCKER_ONLY_POLICY.md](DOCKER_ONLY_POLICY.md)

## クイックスタート

通常は repo root で以下を実行します。

```powershell
cd /d C:\apps\TimelineForWindowsCodex
.\start.bat
.\cli.bat settings status
.\cli.bat items refresh --json
.\cli.bat items download --to C:\TimelineData\windows-codex-downloads --json
```

動作確認をまとめて行う場合:

```powershell
.\test-operational.bat
```

## できること

- Docker Compose で固定 mount された Codex 履歴ディレクトリを読みます。
- `sessions/**/*.jsonl`, `session_index.jsonl`, archived `thread_reads`, `state_5.sqlite` fallback metadata から thread を見つけます。
- thread ごとに master ディレクトリを作ります。
- 会話本文を `timeline.json` に保存します。
- source と変換情報を `convert_info.json` に保存します。
- item 一覧は新しい順で表示し、必要な場合だけページングできます。
- source と変換設定が変わっていない thread は再生成をスキップします。
- 必要なときだけ日時付き ZIP を作ります。

## やらないこと

- Web UI はありません。
- master 出力先に job/run directory は作りません。
- `current.json` や `refresh-history.jsonl` は作りません。
- source の Codex transcript data は編集しません。
- `state_5.sqlite` を会話本文の正本として扱いません。
- binary attachment 本体は出力しません。
- カスタム指示の厳密な保存時刻は復元しません。
- tool call、terminal output、reasoning summary、細かい file diff は通常の `timeline.json` に入れません。

## 設定

通常運用では repo 直下のローカル設定を使います。

```text
C:\apps\TimelineForWindowsCodex\settings.json
```

`settings.json` は Git 管理しません。`.env` と同じく、各 PC 固有の master output root を持つためです。存在しない場合、launcher が `settings.example.json` から自動作成します。

主な項目:

- `schemaVersion`: 設定ファイル形式のバージョン
- `outputRoot`: 固定 master 出力先

Codex の source root はユーザー設定にしません。Docker Compose が現在の Codex home と既知のバックアップ場所を read-only で固定 mount します。

- `C:\Users\amano\.codex` -> `/input/codex-home`
- `C:\Codex\archive\migration-backup-2026-03-27\codex-home` -> `/input/codex-backup`

標準例:

```json
{
  "schemaVersion": 1,
  "outputRoot": "C:\\TimelineData\\windows-codex"
}
```

archived source は必ず読みます。tool-output log、terminal output、compaction recovery はユーザー設定にはしません。会話本文は後から LLM 分析できる証拠として残すため、URL / email / token の redaction は行いません。

## 出力契約

master 出力:

```text
<masterPath>/
  <thread_id>/
    convert_info.json
    timeline.json
```

download ZIP:

```text
README.md
items/
  <thread_id>/
    convert_info.json
    timeline.json
```

`timeline.json` は最終生成物です。

```json
{
  "schema_version": 1,
  "application": "TimelineForWindowsCodex",
  "thread_id": "...",
  "title": "...",
  "created_at": "...",
  "updated_at": "...",
  "messages": [
    {
      "role": "user",
      "created_at": "...",
      "text": "..."
    }
  ]
}
```

`convert_info.json` には、source fingerprint、変換設定、件数、既知の欠損情報を入れます。

## CLI

Windows では `.bat` launcher を安定した正面玄関にします。中では PowerShell 実装を適切な実行ポリシーで呼び出します。repo root で実行します。

```powershell
.\cli.bat settings init
.\cli.bat settings status
.\cli.bat settings master show
.\cli.bat settings master set C:\TimelineData\windows-codex

.\cli.bat items list --json
.\cli.bat items list --page 2 --page-size 50 --json
.\cli.bat items list --all --json
.\cli.bat items refresh --json
.\cli.bat items refresh --download-to C:\TimelineData\windows-codex-downloads --json
.\cli.bat items download --to C:\TimelineData\windows-codex-downloads
```

補足:

- `items list` は `updated_at` の新しい順です。最新 item が先頭に出ます。
- `items list` の既定は全件取得です。
- ページングしたい場合だけ `--page` / `--page-size` を指定します。ページング時の `--page-size` 既定値は `100` です。
- `--all` は明示的に全件を返し、`--page` / `--page-size` より優先します。
- `--item-id` を省略すると、見つかった全 thread が対象です。
- `--item-id` は複数回指定できます。カンマ区切りも使えます。
- `items refresh` は master 出力先を更新します。
- `items download` は現在の master から ZIP を作ります。
- 通常運用では host Python 直接実行をブロックします。テスト時だけ `TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1` を使います。

## Docker Compose

Docker Compose は、project service container である `timeline-for-windows-codex-worker-1` を1つ維持し、CLI launcher は `docker compose exec` でその中に入って CLI を実行します。CLI 実行時は `--no-build` で既存 worker を起動するだけにし、image の build / rebuild が必要な場合は `start.bat` を使います。CLI 実行のたびに `worker-run-*` の一時 container を作らない方針です。ブラウザ UI はありません。

```powershell
cp .env.example .env
.\start.bat
.\cli.bat settings status
.\cli.bat items refresh --json
```

source mount は read-only です。`settings.json` は container 内の `/shared/app-data/settings.json` に mount されます。

運用テストでは本番の `settings.json` を書き換えません。`HOST_TFWC_SETTINGS_FILE`, `HOST_TFWC_APP_DATA`, `HOST_TFWC_DOWNLOADS`, `COMPOSE_PROJECT_NAME` を一時値へ差し替え、fixture 入力と一時出力先だけを使います。

worker service container を停止:

```powershell
.\stop.bat
```

Docker resource をアンインストール:

```powershell
.\uninstall.bat
```

アンインストールスクリプトは、Codex source 履歴、設定済みの `outputRoot`、`downloads` は削除しません。app-data Docker volume や local `settings.json` を削除する前には別途確認します。

## テスト

Unit test:

```bash
TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1 \
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
```

Docker production-like smoke test:

```powershell
python tests/smoke/run_docker_compose_refresh.py
```

この smoke test は refresh を 2 回実行し、master 契約、download ZIP 契約、2 回目の unchanged skip を確認します。
既定では集計だけを出力します。item 単位の詳細デバッグが必要な場合だけ `--include-full-payload` を指定します。

ローカル `cli.ps1` download smoke test:

```powershell
python tests/smoke/run_cli_ps1_download.py
```

このテストは一時 settings path に fixture 用の `settings.json` を作成し、専用 Docker Compose project で `cli.ps1 items refresh` と `cli.ps1 items download` を実行して ZIP 構成を検証します。本番用の `settings.json` と通常の worker service container は変更しません。

Raw source to timeline fidelity audit:

```powershell
python tests/smoke/run_fidelity_audit.py
```

この audit は代表 source の raw transcript から期待される message chain を読み、生成済みまたは一時生成した `timeline.json` / `convert_info.json` と照合します。role、時刻、本文、添付ラベル、message count、旧 `thread.json` / `convert.json` の不在を確認します。

Windows launcher operational smoke test:

```powershell
python tests/smoke/run_windows_launcher_flow.py
```

このテストは `start.bat`、`cli.bat settings status`、`cli.bat items refresh`、`cli.bat items download`、`stop.bat` を順番に実行します。一時 settings path、fixture source、一時 Docker Compose project を使うため、本番用の `settings.json`、通常の worker service container、通常の master 出力先は変更しません。

通常の安定性確認をまとめて実行する場合:

```powershell
.\test-operational.bat
```

これは `cli.ps1` download smoke test、raw source to timeline fidelity audit、Windows launcher operational smoke test、Docker production-like smoke test を順番に実行します。テスト用の一時 settings / source / output を使うため、通常運用の master 出力先は変更しません。
