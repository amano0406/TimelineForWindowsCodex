# TimelineForWindowsCodex

`TimelineForWindowsCodex` は、Windows ローカルにある Codex Desktop 履歴を読み、スレッド単位の JSON 生成物として管理する CLI 専用ツールです。

English README: [README.md](README.md)

この製品の役割は、固定された master 出力先を最新化し、必要なときだけ ZIP として取り出せる状態にすることです。読みやすい全体タイムライン化や要約は後段の Timeline 製品や LLM に任せます。

## できること

- 複数の Codex 履歴ディレクトリを固定設定として読みます。
- `sessions/**/*.jsonl`, `session_index.jsonl`, archived `thread_reads`, `state_5.sqlite` fallback metadata から thread を見つけます。
- thread ごとに master ディレクトリを作ります。
- 会話本文を `thread.json` に保存します。
- source と変換情報を `convert_info.json` に保存します。
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
- tool call、terminal output、reasoning summary、細かい file diff は通常の `thread.json` に入れません。

## 設定

通常運用では repo 直下のローカル設定を使います。

```text
C:\apps\TimelineForWindowsCodex\settings.json
```

`settings.json` は Git 管理しません。`.env` と同じく、各 PC 固有の source root と master output root を持つためです。存在しない場合、launcher が `settings.example.json` から自動作成します。

主な項目:

- `source_roots`: 読み取る Codex 履歴ディレクトリ
- `outputs_root`: 固定 master 出力先
- `redaction_profile`: `strict` または `loose`
- `include_archived_sources`: archived thread reads を含めるか
- `include_tool_outputs`: 互換項目。通常の `thread.json` には tool-output log を入れません
- `include_compaction_recovery`: compaction `replacement_history` からの追加復元

## 出力契約

master 出力:

```text
<masterPath>/
  <thread_id>/
    convert_info.json
    thread.json
```

download ZIP:

```text
README.md
items/
  <thread_id>/
    convert_info.json
    thread.json
```

`thread.json` は最終生成物です。

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

Windows では PowerShell が正面玄関です。repo root で実行します。

```powershell
.\cli.ps1 settings init
.\cli.ps1 settings status
.\cli.ps1 settings inputs list
.\cli.ps1 settings inputs add /input/codex-home
.\cli.ps1 settings inputs remove input-1234abcd
.\cli.ps1 settings inputs clear
.\cli.ps1 settings master show
.\cli.ps1 settings master set /shared/outputs

.\cli.ps1 items list --json
.\cli.ps1 items refresh --json
.\cli.ps1 items refresh --download-to /shared/downloads --json
.\cli.ps1 items download --to /shared/downloads
```

補足:

- `--item-id` を省略すると、見つかった全 thread が対象です。
- `--item-id` は複数回指定できます。カンマ区切りも使えます。
- `items refresh` は master 出力先を更新します。
- `items download` は現在の master から ZIP を作ります。
- 通常運用では host Python 直接実行をブロックします。テスト時だけ `TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1` を使います。

## Docker Compose

Docker Compose は、`cli.ps1` から呼ばれたときだけ Python worker CLI を動かします。この製品では常駐 worker container を使いません。ブラウザ UI もありません。

```powershell
cp .env.example .env
.\cli.ps1 settings status
.\cli.ps1 items refresh --json
```

source mount は read-only です。`settings.json` は container 内の `/shared/app-data/settings.json` に mount されます。

Docker resource を停止:

```powershell
.\stop.ps1
```

Docker resource をアンインストール:

```powershell
.\uninstall.ps1
```

アンインストールスクリプトは、Codex source 履歴、`outputs`、`downloads` は削除しません。app-data Docker volume や local `settings.json` を削除する前には別途確認します。

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
