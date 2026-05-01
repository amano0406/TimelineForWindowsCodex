# TODO

このファイルは、`TimelineForWindowsCodex` のプロジェクトオーナー目線の実装チェック表です。

方針:

- この製品は CLI-only とする。
- Web UI は製品責務から外す。
- source transcript data は削除・上書き・大量移動しない。
- export contract は維持する。
- 通常運用は固定 settings と `items refresh` を主導線にする。
- 複数入力ディレクトリと固定出力先を settings で管理する。
- 通常実行は Docker Compose 経由に限定する。
- Windows 利用者向けの正面玄関は PowerShell とする。
- WSL は自動テスト・開発検証用の裏口として残す。

## A. プロダクトの使命

- [x] Windows 版 Codex のローカル履歴を、LLM に渡しやすい ZIP / JSON 系成果物へ変換できる
- [x] 主目的を「raw に近い会話保存」に置いている
- [x] 主単位を merged global timeline ではなく thread にしている
- [x] Web UI なしで CLI から実行できる

## B. 会話の原文保持

- [x] ユーザー発話、アシスタント発話、thread ローカル system 情報の連鎖を thread ごとに保持できる
- [x] 各発話に日時を保持できる
- [x] source に mode 情報がある場合は保持できる
- [x] source に添付情報がある場合は、添付ファイル名またはラベルを保持できる
- [x] 非テキスト添付は、まずファイル名またはラベルとして扱う方針になっている
- [x] 任意指定時に圧縮履歴の `replacement_history` から user / assistant message を復元できる
- [x] 通常の `thread.json` には tool call / terminal output / reasoning summary を混ぜない

## C. Thread 単位の出力契約

- [x] master root 直下に `<thread_id>/` を作成できる
- [x] thread ごとに独立した `<thread_id>/thread.json` を生成できる
- [x] thread ごとに独立した `<thread_id>/convert.json` を生成できる
- [x] export ルートに `README.md` を生成できる
- [x] `readme.html` / `threads/index.md` / `threads/<thread_id>.md` を通常 ZIP から外している
- [x] 単一 / 複数 / 全 thread の選択を前提にした出力契約になっている
- [x] ZIP にまとめて配布できる
- [x] 日付絞り込みをこの製品の責務から外している

## D. Thread 名の扱い

- [x] thread 名は「確定 rename event」ではなく「観測時点」として扱っている
- [x] thread 名の観測情報を thread ローカル情報として保持できる
- [x] `session_index.jsonl.thread_name` を thread 名 source として使っている
- [x] archived `thread_reads` の `thread.name` を thread 名 source として使っている
- [x] `state_5.sqlite` を thread 名の正本として使わない実装になっている

## E. 環境台帳

- [x] thread 内の出来事と、環境全体の変更を分離できる
- [x] カスタム指示、モデル設定、client runtime を environment ledger に集約できる
- [x] 環境情報を重複除去して ledger 化できる
- [x] カスタム指示の時刻は「実保存時刻」ではなく「観測時点」として扱う実装になっている
- [x] environment ledger は run directory の診断情報として分離している

## F. 入力源

- [x] `session_index.jsonl` を入力源として扱える
- [x] `sessions/**/*.jsonl` を入力源として扱える
- [x] archived `thread_reads/*.json` を入力源として扱える
- [x] `state_5.sqlite` を discovery / fallback metadata 用として扱える
- [x] Docker Compose では source root を read-only mount する構成になっている

## G. 実行面

- [x] CLI で `settings / items / runs` の通常コマンド群を持っている
- [x] CLI で読み取り対象を確認する `items list` を持っている
- [x] CLI で最新ZIPを指定先へコピーする `items download` を持っている
- [x] CLI で refresh から ZIP コピーまで行う `items refresh --download-to` を持っている
- [x] CLI で item id 指定なしなら全 thread 対象にできる
- [x] CLI で item id を複数指定できる
- [x] Docker Compose は worker CLI を起動する
- [x] Web UI 実装を削除済み
- [x] 複数 source root を settings に保存できる
- [x] output root を settings に保存できる
- [x] repo root の `settings.example.json` を Git 管理している
- [x] repo root の `settings.json` を Git 管理外にしている
- [x] host-side 開発検証時の既定 settings path を repo root `settings.json` にしている
- [x] Docker Compose では `TIMELINE_FOR_WINDOWS_CODEX_SETTINGS_PATH` で永続 volume 側の settings を使える
- [x] ホスト上の直接 CLI 実行を通常運用では停止できる
- [x] 自動テストだけ `TIMELINE_FOR_WINDOWS_CODEX_ALLOW_HOST_RUN=1` でホスト実行を許可できる
- [x] Docker の ENTRYPOINT / CMD を CLI コマンド指定しやすい形にしている
- [x] PowerShell wrapper から Docker Compose 経由で CLI を実行できる
- [x] WSL / host shell は自動テスト・開発検証用の裏口として扱う方針を明記している
- [x] `settings init` で通常設定を初期化できる
- [x] `items refresh` で settings の source root / output root を使える
- [x] 変化していない thread は前回成果物を再利用できる
- [x] ZIP ファイル名に run id 由来の日時情報を含められる

## H. 出力内容の説明責任

- [x] export `README.md` 上で「何が含まれるか」を説明している
- [x] run directory の `fidelity_report.*` 上で「既知の欠損・未収録」を説明している
- [x] run ごとの missing source や fidelity gap を明示する専用レポートを生成できる
- [x] `catalog.json` と `update_manifest.json` を生成できる
- [x] `processing_profile.json` で重い thread を確認できる
- [x] `current.json` と `refresh-history.jsonl` を更新できる

## I. 動作確認

- [x] worker integration tests がある
- [x] CLI `items list` の fixture 確認がある
- [x] CLI `items refresh` の単一 / 複数 / 全 thread export 確認がある
- [x] CLI `runs list` / `runs show` 確認がある
- [x] CLI `settings` / `items refresh` の fixture 確認がある
- [x] CLI `settings init` / `items download` の fixture 確認がある
- [x] CLI `items refresh --download-to` の fixture 確認がある
- [x] CLI `settings status` / `items refresh --help` の実行確認がある
- [x] PowerShell wrapper の `help` / `settings status` 実行確認がある
- [x] 本物の `.codex` を一時出力先で読む production-like smoke test がある
- [x] Docker Compose 経由で本物の `.codex` を一時出力先で読む production-like smoke test がある
- [x] ZIP に `README.md` と `<thread_id>/convert.json` / `<thread_id>/thread.json` が入ることを確認している

## J. まだ未実装の大枠項目

- [ ] 確定的な thread rename event の復元
- [ ] カスタム指示の厳密な保存時刻履歴の復元
- [ ] fine-grained file edit diff の export
- [ ] バイナリ添付本体の export
- [ ] archived `thread_reads` の richer item coverage
- [ ] state database からの広範な enrichment
