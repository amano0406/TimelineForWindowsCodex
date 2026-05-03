# TODO

`TimelineForWindowsCodex` のプロジェクトオーナー目線チェック表です。

方針:

- CLI-only。Web UI は製品責務から外す。
- source transcript data は削除・上書き・大量移動しない。
- 固定 settings と `items refresh` / `items download` を主導線にする。
- master は `<thread_id>/convert_info.json` と `<thread_id>/timeline.json` だけを正本にする。
- job/run directory、`current.json`、`refresh-history.jsonl` は通常出力として持たない。
- 通常実行は Docker Compose 経由。Windows の正面玄関は PowerShell。

## A. プロダクトの使命

- [x] Windows Codex のローカル履歴を、LLM に渡しやすい JSON / ZIP に変換できる
- [x] 主目的を raw に近い会話保存に置いている
- [x] 主単位を merged global timeline ではなく thread にしている
- [x] Web UI なしで CLI から実行できる

## B. 会話の保持

- [x] ユーザー発話、アシスタント発話、source 由来の system 相当情報を thread ごとに保持できる
- [x] 各発話に日時を保持できる
- [x] source に mode 情報がある場合は保持できる
- [x] source に添付情報がある場合は、添付ファイル名またはラベルを保持できる
- [x] 通常の `timeline.json` には tool call / terminal output / reasoning summary を混ぜない
- [x] 任意指定時に compaction `replacement_history` から user / assistant message を復元できる

## C. 出力契約

- [x] master root 直下に `<thread_id>/` を作成できる
- [x] `<thread_id>/timeline.json` を生成できる
- [x] `<thread_id>/convert_info.json` を生成できる
- [x] 旧 `convert.json` を master 正本にしない
- [x] download ZIP は `README.md` と `items/<thread_id>/convert_info.json` / `items/<thread_id>/timeline.json` に限定している
- [x] `readme.html` / `threads/index.md` / `threads/<thread_id>.md` を通常 ZIP から外している
- [x] 単一 / 複数 / 全 thread の選択を前提にした出力契約になっている
- [x] 日付絞り込みをこの製品の責務から外している

## D. 入力源

- [x] `sessions/**/*.jsonl` を本文 source として扱える
- [x] `session_index.jsonl` を discovery / thread name source として扱える
- [x] archived `thread_reads/*.json` を入力源として扱える
- [x] `state_5.sqlite` を discovery / fallback metadata 用として扱える
- [x] Docker Compose では source root を read-only mount する構成になっている

## E. 実行面

- [x] CLI で `settings` と `items` の通常コマンド群を持っている
- [x] `runs` コマンドを通常ユーザー面から外している
- [x] CLI で読み取り対象を確認する `items list` を持っている
- [x] CLI で master を更新する `items refresh` を持っている
- [x] CLI で ZIP を指定先に作る `items download` を持っている
- [x] CLI で refresh から ZIP 作成まで行う `items refresh --download-to` を持っている
- [x] CLI で item id 指定なしなら全 thread 対象にできる
- [x] CLI で item id を複数指定できる
- [x] source root は settings に保存せず、Docker Compose の read-only mount として固定できる
- [x] master output root を settings に保存できる
- [x] repo root の `settings.example.json` を Git 管理している
- [x] repo root の `settings.json` を Git 管理外にしている
- [x] ホスト上の直接 CLI 実行を通常運用では停止できる
- [x] PowerShell wrapper から Docker Compose 経由で CLI を実行できる

## F. 差分更新

- [x] source fingerprint と変換設定から thread 単位の cache key を作れる
- [x] 変化していない thread は既存 master item を再利用できる
- [x] 変化がある thread だけ `timeline.json` / `convert_info.json` を再生成できる
- [x] ZIP ファイル名に日時情報を含められる

## G. 動作確認

- [x] worker integration tests がある
- [x] CLI `items list` の fixture 確認がある
- [x] CLI `items refresh` の単一 / 複数 / 全 thread export 確認がある
- [x] CLI `settings init` / `items download` の fixture 確認がある
- [x] CLI `items refresh --download-to` の fixture 確認がある
- [x] 本物または fixture の `.codex` を一時出力先で読む production-like smoke test がある
- [x] Docker Compose 経由の production-like smoke test がある
- [x] ローカル `cli.ps1` 経由の download smoke test がある
- [x] Windows 正面玄関の `start.bat` / `cli.bat` / `stop.bat` を通す launcher smoke test がある
- [x] ZIP に `README.md` と `items/<thread_id>/convert_info.json` / `items/<thread_id>/timeline.json` が入ることを確認している

## H. 低優先または範囲外

- [ ] 確定的な thread rename event の復元
- [ ] カスタム指示の厳密な保存時刻履歴の復元
- [ ] fine-grained file edit diff の export
- [ ] バイナリ添付本体の export
- [ ] archived `thread_reads` の richer item coverage
- [ ] state database からの広範な enrichment
