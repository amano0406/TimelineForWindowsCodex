# TODO

このファイルは、`TimelineForWindowsCodex` の**プロジェクトオーナー目線の実装チェック表**です。

差分更新型 UI / 成果物更新管理の設計と 4 軸チェックリストは `docs/UPDATE_UI_INCREMENTAL_DESIGN.md` を参照する。

判定ルール:

- この表は**過去スレッドではなく、現在の repo 内の実コード**だけを根拠に更新する
- 今回の判定軸は **実装有無のみ**
- E2E、CLI 実行、web 操作、ユニットテスト、smoke test はこの表では扱わない
- `[x]` は「実装あり」、`[ ]` は「未実装または現コード上は確認できない」

## A. プロダクトの使命

- [x] Windows 版 Codex のローカル履歴を、LLM に渡しやすい ZIP / Markdown / JSON 系成果物へ変換できる  
  根拠: `worker/src/timeline_for_windows_codex_worker/processor.py`, `worker/src/timeline_for_windows_codex_worker/timeline.py`
- [x] 主目的を「raw に近い会話保存」に置いている  
  根拠: `render_thread_timeline()` が発話本文を thread transcript として出力し、`render_export_readme_html()` も raw message chain を主対象として説明している
- [x] 主単位を merged global timeline ではなく thread にしている  
  根拠: `ThreadSelection`, `threads/<thread_id>/timeline.md`, `threads/index.md`, `readme.html`

## B. 会話の原文保持

- [x] ユーザー発話とアシスタント発話の連鎖を thread ごとに保持できる  
  根拠: `parse_thread_transcript_entries()`, `render_thread_timeline()`
- [x] 各発話に日時を保持できる  
  根拠: transcript entry に `timestamp` を持ち、thread markdown 見出しに表示している
- [x] source に mode 情報がある場合は保持できる  
  根拠: `turn_context` の `collaboration_mode` を transcript entry の `mode` として反映している
- [x] source に添付情報がある場合は、添付ファイル名またはラベルを保持できる  
  根拠: `_extract_response_message_transcript_parts()`, `_extract_event_message_attachments()`, `_extract_thread_read_attachments()`
- [x] 非テキスト添付は、まずファイル名またはラベルとして扱う方針になっている  
  根拠: `_extract_attachment_label()` と `_file_label_from_unknown_payload()` が添付本体ではなく表示用ラベルを返す

## C. thread 単位の出力契約

- [x] thread ごとに独立した markdown を生成できる  
  根拠: `processor.py` が `threads/<thread_id>/timeline.md` を生成する
- [x] export 上の thread ファイル名を `threads/<thread_id>.md` に固定している  
  根拠: `export_thread_markdown_name()` が thread id のみで export 名を決める
- [x] `readme.html` を入口として生成できる  
  根拠: `render_export_readme_html()` と `processor.py`
- [x] `threads/index.md` を生成できる  
  根拠: `render_timeline_index()` と `processor.py`
- [x] 単一 / 複数 / 全 thread の選択を前提にした出力契約になっている  
  根拠: `JobRequest.selected_threads`, web の `SelectedThreadIds`, CLI の `--thread-id`
- [x] ZIP にまとめて配布できる  
  根拠: `build_run_archive()` が `TimelineForWindowsCodex-export.zip` を生成する

## D. thread 名の扱い

- [x] thread 名は「確定 rename event」ではなく「観測時点」として扱っている  
  根拠: thread markdown に observation point と明記し、confirmed rename event とは扱っていない
- [x] thread 名の観測情報を thread ローカル情報として保持できる  
  根拠: `ObservedThreadName`, `observed_thread_names`, `render_thread_timeline()`
- [x] `session_index.jsonl.thread_name` を thread 名 source として使っている  
  根拠: web `MergeSessionIndexAsync()`, worker `discovery.py::_merge_session_index()`
- [x] archived `thread_reads` の `thread.name` を thread 名 source として使っている  
  根拠: web `MergeThreadReadFilesAsync()`, worker `discovery.py::_merge_thread_read_files()`
- [x] `state_5.sqlite` を thread 名の正本として使わない実装になっている  
  根拠: web `MergeStateCatalogAsync()` と worker `discovery.py::_merge_state_catalog()` は `title` を読まず、`id / rollout_path / updated_at / cwd / first_user_message` のみ扱う

## E. 環境台帳

- [x] thread 内の出来事と、環境全体の変更を分離できる  
  根拠: `threads/*` と `environment/*` を別出力にしている
- [x] カスタム指示、モデル設定、client runtime を environment ledger に集約できる  
  根拠: `parse_thread_environment_observations()`, `build_environment_ledger()`
- [x] 環境情報を重複除去して ledger 化できる  
  根拠: `build_environment_ledger()` が fingerprint 単位で grouped / dedupe している
- [x] カスタム指示の時刻は「実保存時刻」ではなく「観測時点」として扱う実装になっている  
  根拠: `render_environment_ledger_md()` が `first_observed_at` は実保存時刻より後になる場合があると明記している
- [x] thread 側から environment ledger への参照導線を持っている  
  根拠: thread markdown に `../environment/ledger.md` を埋めている

## F. 入力源

- [x] `session_index.jsonl` を入力源として扱える  
  根拠: web `MergeSessionIndexAsync()`, worker `discovery.py::_merge_session_index()`
- [x] `sessions/**/*.jsonl` を入力源として扱える  
  根拠: web `MergeSessionFilesAsync()`, worker `discovery.py::_merge_session_files()`, worker `parse_sessions.py`
- [x] archived `thread_reads/*.json` を入力源として扱える  
  根拠: web `MergeThreadReadFilesAsync()`, worker `discovery.py::_merge_thread_read_files()`, worker `parse_sessions.py`
- [x] `state_5.sqlite` を discovery / fallback metadata 用として扱える  
  根拠: web `MergeStateCatalogAsync()`, worker `discovery.py::_merge_state_catalog()`
- [x] source root を read-only 前提で取り込む構成になっている  
  根拠: `docker-compose.yml` で `/input/codex-home`, `/input/codex-backup`, `/input/codex-root` を `:ro` mount している

## G. 実行面

- [x] web UI で new job / jobs list / details / settings を持っている  
  根拠: `web/Pages/Jobs/New.cshtml*`, `web/Pages/Jobs/Index.cshtml*`, `web/Pages/Jobs/Details.cshtml*`, `web/Pages/Settings.cshtml*`
- [x] web 側で thread discovery、選択、job 作成、job 詳細表示、ZIP download の導線を持っている  
  根拠: `New.cshtml.cs`, `RunStore.cs`, `Program.cs`
- [x] CLI で `discover / create-job / run / list-jobs / show-job / process-job / daemon` を持っている  
  根拠: `worker/src/timeline_for_windows_codex_worker/cli.py`
- [x] Docker Compose で web / worker 分離構成になっている  
  根拠: `docker-compose.yml`
- [x] 日本語 / 英語 UI を持っている  
  根拠: `web/Resources/Locales/ja.json`, `web/Resources/Locales/en.json`, `LanguageService`

## H. 選択 UX

- [x] web で thread 一覧の filter UI を持っている  
  根拠: `Jobs/New.cshtml` の search input と client-side filter script
- [x] web で all / visible / clear の selection helper を持っている  
  根拠: `Jobs/New.cshtml` の selection helper buttons
- [x] web で初期状態を「検出した thread 全選択」にできる  
  根拠: `New.cshtml.cs::SelectAllThreadsIfEmpty()`
- [x] CLI で thread id 指定なしなら全 thread 対象にできる  
  根拠: `cli.py::_select_threads()` が `--thread-id` 未指定時に discovered 全件を返す

## I. 出力内容の説明責任

- [x] export `readme.html` 上で「何が含まれるか」を説明している  
  根拠: `render_export_readme_html()` の `Included / 含まれるもの`
- [x] export `readme.html` 上で「何を含めないか」を説明している  
  根拠: `render_export_readme_html()` の `Not included / 含めないもの`
- [x] run ごとの missing source や fidelity gap を明示する専用レポートを生成できる  
  根拠: `processor.py` が `fidelity_report.md` / `fidelity_report.json` を生成し、`build_run_archive()` と `render_export_readme_html()` / `render_timeline_index()` から参照できる

## J. まだ未実装の大枠項目

- [ ] 確定的な thread rename event の復元  
  根拠: 現行実装は observation point モデルであり、rename event モデルは持っていない
- [ ] カスタム指示の厳密な保存時刻履歴の復元  
  根拠: ledger は `first_observed_at` ベースで、実保存時刻とは明示的に分けている
- [ ] fine-grained file edit diff の export  
  根拠: `render_export_readme_html()` で not included と明記している
- [ ] バイナリ添付本体の export  
  根拠: `render_export_readme_html()` で not included と明記し、parser もラベル抽出に留めている
- [ ] archived `thread_reads` の richer item coverage  
  根拠: `_parse_thread_read_events()` / `_parse_thread_read_transcript_entries()` は `userMessage`, `agentMessage`, `reasoning`, `plan`, `contextCompaction` 中心で、それ以外の item type を広く扱っていない
- [ ] state database からの広範な enrichment  
  根拠: `state_5.sqlite` は thread catalog / fallback metadata 用に留まり、広い補完モデルは持っていない

## K. 動作確認 (E2E)

- [x] CLI `discover` で current session fixture と archived `thread_reads` fixture を列挙できた  
  確認経路: `python3 -m timeline_for_windows_codex_worker discover --primary-root tests/fixtures/codex-home-min --backup-root tests/fixtures/archived-root-min --include-archived-sources --format json`
- [x] CLI `create-job` で、発見した全 thread を含む pending job を作成できた  
  確認経路: `python3 -m timeline_for_windows_codex_worker create-job ... --format json`
- [x] CLI `run` で単一 thread export を完走できた  
  確認経路: `--thread-id 11111111-2222-3333-4444-555555555555`
- [x] CLI `run` で明示的な複数 thread export を完走できた  
  確認経路: `--thread-id 11111111-2222-3333-4444-555555555555 --thread-id aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee`
- [x] CLI `run` で thread id 未指定時に全 thread export を完走できた  
  確認経路: `python3 -m timeline_for_windows_codex_worker run ... --format json`
- [x] CLI `list-jobs` で pending / completed job 一覧を確認できた  
  確認経路: `python3 -m timeline_for_windows_codex_worker list-jobs --format json`
- [x] CLI `show-job` で request / status / result / manifest / selected_threads を確認できた  
  確認経路: `python3 -m timeline_for_windows_codex_worker show-job <job_id> --format json`
- [x] CLI 生成物で、thread ごとの raw 会話連鎖、日時、mode、observed thread name、environment ledger 参照を確認できた  
  確認経路: 生成された `threads/*/timeline.md` を目視確認
- [x] CLI 生成物で、添付ファイル名ラベルの出力を確認できた  
  確認経路: session fixture に `000.txt` 添付ラベルを含め、生成された `timeline.md` で確認
- [x] CLI 生成 ZIP に `readme.html`, `threads/index.md`, `threads/<thread_id>.md`, `environment/*` が含まれることを確認できた  
  確認経路: 生成 ZIP の中身を確認
- [x] CLI 生成物で、`fidelity_report.md` / `fidelity_report.json` が生成され、ZIP に同梱されることを確認できた  
  確認経路: `run-20260421T171008-2b1c33438342` の生成物と ZIP を確認
- [x] web 経路で `jobs/new -> create -> details -> jobs -> download` を session JSONL fixture に対して完走できた  
  確認経路: `tests/smoke/run_web_smoke.py`
- [x] web 経路で `jobs/new -> create -> details -> jobs -> download` を `state_5.sqlite + archived thread_reads` fixture に対して完走できた  
  確認経路: `tests/smoke/run_web_smoke.py`
- [x] web で thread discovery filter と selection helper を確認できた  
  確認経路: `tests/smoke/run_web_smoke.py` が `Filter by thread name, ID, or working folder` と `Select visible` を検証
- [x] web download が有効な ZIP archive を返すことを確認できた  
  確認経路: `tests/smoke/run_web_smoke.py`
- [x] web 経路で、`state_5.sqlite` の title ではなく archived thread name が表示に使われることを確認できた  
  確認経路: smoke 用 state catalog の title は別値だが、期待表示は `Archived timeline source` で通過
- [x] Docker Compose を使った E2E 動作確認を実施できた  
  確認経路: fixture を mount する一時 `.env` で `docker compose up --build -d` を実行し、`/jobs/new -> Execute -> Completed -> download` を HTTP 経路で確認
