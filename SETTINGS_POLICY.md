# Settings Policy

この文書は、`TimelineForWindowsCodex` で採用した settings 管理方針を、他の Timeline 系プロダクトへ共有するための短いメモです。

## 結論

- アプリの永続設定は `settings.json` として扱う。
- `settings.json` は Git 管理しない。
- Git 管理するのは `settings.example.json` のみ。
- 通常運用では repo root の `settings.json` を host 正本にし、container 内では `/shared/app-data/settings.json` として読む。
- テストや検証では `HOST_TFWC_SETTINGS_FILE` で settings path を一時ファイルへ差し替える。
- `.env` は Docker mount path や runtime override 向けに残す。
- 本番設定とテスト設定を同じ `settings.json` に混ぜない。

## 役割分担

`settings.json` に置くもの:

- 出力ディレクトリ

`.env` に置くもの:

- settings file の host path
- app-data の host path
- downloads の host path
- Docker の host mount path
- container 内の runtime path
- API key など、必要になった場合の環境依存値

## 理由

- 通常運用では `settings.json` を repo root に置くと、設定ファイルの場所を別途覚える必要がない。
- テスト時は settings path を一時ファイルへ差し替えると、本番設定を書き換えずに運用テストできる。
- `settings.example.json` を配ることで、新しい環境でも初期設定の形が分かる。
- `settings.json` を Git 管理外にすると、個人のローカルパスや出力先が commit に混ざらない。
- `.env` と同じ運用にすると、非エンジニアにも「自分の環境用ファイル」として説明しやすい。

## TimelineForWindowsCodex での具体例

Git 管理するファイル:

- `settings.example.json`

Git 管理しないファイル:

- `settings.json`
- `.env`

Docker Compose container 内の settings path:

- `/shared/app-data/settings.json`

通常運用の host settings:

- `C:\apps\TimelineForWindowsCodex\settings.json`

運用テストの host settings:

- `C:\TimelineData\tfwc-...\settings\settings.json`

補足:

- 通常実行は Docker Compose 経由に限定する。
- Windows 利用者向けの入口は PowerShell wrapper にする。
- テストは専用 settings path、専用 app-data、専用 source mount、専用 output root を使う。
