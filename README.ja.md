# TimelineForWindowsCodex

`TimelineForWindowsCodex` は、Windows ローカルにある Codex Desktop の履歴を読み、thread 単位の master 生成物、診断情報、ZIP 受け渡しパッケージに変換する CLI 専用ツールです。

English README: [README.md](README.md)

## 役割

- 複数の Codex 履歴ディレクトリを固定設定として読みます。
- `sessions/**/*.jsonl` を主な会話本文 source として扱います。
- archived `thread_reads` と `state_5.sqlite` は補助 source として扱います。
- thread ごとに raw に近いユーザー / アシスタント / システム会話 `thread.json` を生成します。
- thread ごとに変換情報をまとめた `convert.json` を生成します。
- 圧縮履歴の `replacement_history` は、明示的に有効化した場合だけ復元対象にします。
- カスタム指示、モデル、client runtime などは run directory 内の診断情報に分離します。
- 欠損や未収録範囲は `fidelity_report.*` に明示します。
- 最新成果物は ZIP として取り出せます。
- 変化していない thread は前回成果物を再利用します。
- 日付絞り込みや読みやすい global timeline 表示は、この製品ではなく後段の timeline 製品の責務です。

## やらないこと

- Web UI はありません。
- source の Codex transcript data は編集しません。
- binary attachment 本体は export しません。
- 確定的な thread rename event は復元しません。観測できた thread 名だけを扱います。
- カスタム指示の厳密な保存時刻は復元しません。観測時点として扱います。

## 実行方針

Windows 利用者向けの正面玄関は PowerShell です。

```powershell
.\tfwc.ps1 <command>
```

内部実行は Docker Compose です。WSL や host Python の直接実行は、自動テスト・開発検証用の裏口です。通常運用では host Python 直接実行はブロックされます。

## CLI の考え方

`TimelineForAudio` と概念をそろえつつ、この製品では source / artifact / job 操作を細かく分けません。利用者向けの主導線は、固定設定、Codex 履歴 item、過去 run の確認です。

| コマンド群 | 役割 |
|---|---|
| `settings` | 固定設定を管理します。入力は複数、master 出力先は 1 つです。 |
| `items` | 読み取れる Codex thread を確認し、最新化し、最新 ZIP を取り出します。 |
| `runs` | 過去の refresh run を確認します。通常操作ではなく、履歴確認・診断用です。 |

## 基本コマンド

初期化と確認:

```powershell
.\tfwc.ps1 settings init
.\tfwc.ps1 settings status
```

入力ディレクトリを設定:

```powershell
.\tfwc.ps1 settings inputs add /input/codex-home
.\tfwc.ps1 settings inputs add /input/codex-backup
.\tfwc.ps1 settings inputs list
.\tfwc.ps1 settings inputs remove input-1234abcd
```

出力先 master を設定:

```powershell
.\tfwc.ps1 settings master set /shared/outputs
.\tfwc.ps1 settings master show
```

item を確認:

```powershell
.\tfwc.ps1 items list --json
```

設定済み入力から最新化:

```powershell
.\tfwc.ps1 items refresh --json
```

最新化して ZIP も指定先へコピー:

```powershell
.\tfwc.ps1 items refresh --download-to /shared/outputs/handoff --json
```

最新 ZIP をコピー:

```powershell
.\tfwc.ps1 items download --to /shared/outputs/handoff
```

過去の実行を確認:

```powershell
.\tfwc.ps1 runs list --json
.\tfwc.ps1 runs show --run-id <run-id> --json
```

明示的な source root で一時的に実行:

```powershell
.\tfwc.ps1 items refresh `
  --primary-root /input/codex-home `
  --include-archived-sources `
  --json
```

item を絞って実行:

```powershell
.\tfwc.ps1 items refresh `
  --primary-root /input/codex-home `
  --item-id 11111111-2222-3333-4444-555555555555 `
  --json
```

## 出力構成

各 refresh は、設定された master 出力先の下に run directory を作ります。

```text
<outputs-root>/
  <run-id>/
    request.json
    status.json
    result.json
    manifest.json
    README.md
    fidelity_report.json
    fidelity_report.md
    catalog.json
    processing_profile.json
    update_manifest.json
    environment/
    export/TimelineForWindowsCodex-export-<run-id>.zip
  <thread-id>/
    convert.json
    thread.json
  current.json
  refresh-history.jsonl
```

ZIP の中身は、受け渡しに必要な最小構成です。

- `README.md`
- `<thread_id>/convert.json`
- `<thread_id>/thread.json`

`environment/*`, `fidelity_report.*`, `catalog.json`, `processing_profile.json`, `update_manifest.json` は run directory には残しますが、通常のダウンロード ZIP には含めません。

## 設定ファイル

Docker Compose 通常運用では、永続設定は `/shared/app-data/settings.json` に保存されます。

repo にはテンプレートだけを置きます。

```text
C:\apps\TimelineForWindowsCodex\settings.example.json
```

`settings.json` と `.env` は各マシン固有のファイルなので Git 管理しません。

## テスト

host Python での自動テストは、明示的なテスト用 override が必要です。

```bash
TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1 \
PYTHONPATH=/mnt/c/apps/TimelineForWindowsCodex/worker/src \
python3 -m unittest discover -s /mnt/c/apps/TimelineForWindowsCodex/worker/tests -v
```

Docker Compose 経由の本番相当 smoke test:

```powershell
.\tfwc.ps1 smoke
```

## 現在の境界

含まれるもの:

- thread discovery
- 単一 / 複数 / 全 thread export
- raw に近い user / assistant / system 会話 `thread.json`
- 変換情報 `convert.json`
- 任意指定時の圧縮履歴 user / assistant message 復元
- `<thread_id>/thread.json` と `<thread_id>/convert.json`
- observed thread name points
- run directory 内の environment ledger
- run directory 内の fidelity report
- `README.md` と thread ごとの `convert.json` / `thread.json` だけの小さい ZIP export
- current artifact pointer
- refresh history
- unchanged thread artifact reuse
- `settings inputs` / `settings master`
- Docker-only guard

通常の `thread.json` に含めないもの:

- tool call 詳細
- terminal command output
- reasoning summary
- fine-grained file edit diff
- 日付範囲での絞り込み。この製品は取得可能な Codex thread 全体を管理します。

未対応または低優先:

- 確定的な thread rename event の復元
- カスタム指示の厳密な保存時刻履歴
- fine-grained file edit diff
- binary attachment 本体 export
- archived `thread_reads` の richer item coverage
- state database からの広範な enrichment
