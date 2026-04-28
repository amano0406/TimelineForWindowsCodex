# Settings Policy

この文書は、`TimelineForWindowsCodex` で採用した settings 管理方針を、他の Timeline 系プロダクトへ共有するための短いメモです。

## 結論

- アプリの永続設定は `settings.json` として扱う。
- Docker Compose 通常運用では `/shared/app-data/settings.json` を正本にする。
- host-side 開発検証では repo root の `settings.json` を使ってよい。
- `settings.json` は Git 管理しない。
- Git 管理するのは `settings.example.json` のみ。
- `.env` は Docker / runtime / 環境変数向けに残す。
- 実行形態ごとの保存先は、`TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH` のような明示 env で差し替える。

## 役割分担

`settings.json` に置くもの:

- 入力ディレクトリ
- 出力ディレクトリ
- redaction profile
- archived source を読むかどうか
- tool output を読むかどうか

`.env` に置くもの:

- Docker の host mount path
- container 内の runtime path
- settings path の明示 override
- API key など、必要になった場合の環境依存値

## 理由

- Docker 通常運用では named volume に settings を置くと、container 再作成後も設定が残る。
- host-side 開発では `settings.json` を repo root に置くと、設定ファイルの場所を別途覚える必要がない。
- `settings.example.json` を配ることで、新しい環境でも初期設定の形が分かる。
- `settings.json` を Git 管理外にすると、個人のローカルパスや出力先が commit に混ざらない。
- `.env` と同じ運用にすると、非エンジニアにも「自分の環境用ファイル」として説明しやすい。

## TimelineForWindowsCodex での具体例

Git 管理するファイル:

- `settings.example.json`

Git 管理しないファイル:

- `settings.json`
- `.env`

Docker Compose の通常 settings:

- `/shared/app-data/settings.json`

host-side 開発検証 settings:

- `C:\apps\TimelineForWindowsCodex\settings.json`

補足:

- 通常実行は Docker Compose 経由に限定する。
- Windows 利用者向けの入口は PowerShell wrapper にする。
- host-side settings は内部検証用であり、利用者向けの正規導線ではない。
