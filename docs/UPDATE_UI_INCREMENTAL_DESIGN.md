# Update UI / Incremental Artifact Design

更新日: 2026-04-23 Asia/Tokyo

## 目的

`TimelineForWindowsCodex` を、毎回の one-shot export だけではなく、ローカル Codex 履歴の「現在の成果物」を保守できる UI に寄せる。

重視すること:

- ユーザーが「今の成果物は最新か」を UI で判断できる
- 何が追加・変更・未取得・欠損したかを UI で見られる
- `最新化` ボタンで、前回から変わった部分だけを処理できる
- ダウンロード時は、最新状態の全体 ZIP を取得できる
- raw source は read-only のまま扱う
- `readme.html` / `fidelity_report.*` と UI の説明責任を揃える

## 背景

現状は `run` ごとに独立した job と ZIP を作るモデルである。
これは MVP としては分かりやすいが、Codex 履歴のように日々増えるデータでは、毎回全処理すると重くなりやすい。

`TimelineForAudio` は同じ入力・同じ結果を再利用 / skip する考え方を持っている。
`TimelineForWindowsCodex` では、音声ファイル単位ではなく、thread / source file / output artifact 単位で同じ考え方を使う。

## 推奨コンセプト

主語を `job` から `current artifact` に少し寄せる。

- `Source roots`
  - `.codex`, backup `.codex`, archived roots
  - 常に read-only
- `Catalog`
  - source file と thread の既知状態を記録する
  - 前回の fingerprint と今回の fingerprint を比較する
- `Refresh run`
  - `最新化` ボタンで作られる差分更新処理
  - changed / new / missing / unchanged を記録する
- `Current artifact`
  - 最新の全体 export
  - ダウンロード対象は基本的にこれ
- `Update history`
  - いつ何が更新されたか
  - 失敗や部分更新も残す

## 画面方針

### 1. Dashboard

目的:

- 現在の成果物が最新かを一目で見る

表示したいもの:

- last refreshed at
- source roots
- total threads
- total messages
- changed since last refresh
- missing / degraded source count
- current ZIP download
- `最新化` button

### 2. Refresh Details

目的:

- 今回の更新で何が起きたかを見る

表示したいもの:

- state / stage / progress
- current thread
- elapsed
- estimated remaining
- new threads
- changed threads
- unchanged threads
- missing sources
- warnings
- worker log tail

### 3. Thread Coverage

目的:

- どの thread がどこまで取れているかを見る

表示したいもの:

- thread id
- observed thread name
- last source timestamp
- message count
- attachment label count
- rename event count
- environment observation count
- source type
- status: `new / changed / unchanged / missing / degraded`

### 4. Source Coverage

目的:

- 何を読んだか、何を読めなかったかを見る

表示したいもの:

- `session_index.jsonl`
- `sessions/**/*.jsonl`
- `state_5.sqlite`
- archived `thread_reads`
- missing / unreadable files
- large binary-like payload handling

### 5. Export Preview

目的:

- ZIP を開かなくても中身を確認する

表示したいもの:

- `readme.html` preview
- `threads/index.md` preview
- `fidelity_report.md` preview
- `environment/ledger.md` preview
- selected thread preview

## 差分更新モデル

### MVP の fingerprint

最初は file hash か metadata hash で十分。

候補:

- source path
- file size
- file mtime
- SHA-256
- parsed thread id
- parsed message count
- parsed last timestamp

推奨:

- source file fingerprint は `size + mtime + sha256`
- thread fingerprint は `source fingerprints + parser version + render contract version`
- output fingerprint は `thread markdown hash + environment ledger hash + fidelity report hash`

### 更新判定

- `new`
  - catalog に存在しない thread / source
- `changed`
  - catalog の fingerprint と今回 fingerprint が違う
- `unchanged`
  - fingerprint が同じ
- `missing`
  - 前回あった source が今回見つからない
- `degraded`
  - source はあるが、前回より coverage が落ちた

### 処理方針

- changed / new の thread だけ再 parse / 再 render
- unchanged の thread markdown は再利用
- environment ledger は selected source 全体から再構築する
- current ZIP は最新 thread artifacts を集めて再生成する
- download は処理ではなく packaging に近づける

### キャッシュ再利用の注意事項

- キャッシュ再利用は「出力結果が変わらないと判断できる場合だけ」の最適化として扱う
- 判定には source content fingerprint、thread metadata、parser version、render contract version、redaction profile、tool output flag、date filters を含める
- mtime だけでは判断しない。mtime が変わっても content hash が同じなら再利用候補にできる
- parser / renderer の仕様を変えた場合は version を上げ、同じ source でも再生成する
- environment ledger は thread cache から再利用した observations と新規 parse 分を合わせて毎回再構築する

## 保存ファイル案

`app-data` または `outputs` 配下に置く。

```text
artifact-store/
  catalog.json
  current.json
  refresh-history.jsonl
  threads/
    <thread_id>/
      timeline.md
      metadata.json
      source_fingerprints.json
  environment/
    ledger.md
    ledger.json
    observations.jsonl
  exports/
    current.zip
  refresh-runs/
    <refresh_id>/
      request.json
      status.json
      update_manifest.json
      fidelity_report.md
      fidelity_report.json
      logs/worker.log
```

## Job / Refresh lifecycle

```text
queued
  -> discovering
  -> diffing
  -> processing_changed_threads
  -> rebuilding_environment
  -> rebuilding_export
  -> completed
```

失敗時:

```text
failed
  -> FAILURE_REPORT.md
  -> worker.log
  -> previous current artifact remains active
```

## 既存実装との関係

流用するもの:

- current web / worker / Docker Compose 構成
- existing job store
- parser
- renderer
- `fidelity_report.*`
- `environment/*`
- `readme.html`
- CLI command structure

作り替えるもの:

- `run` 中心の UI から `current artifact + refresh history` へ寄せる
- Details UI を inspection 重視にする
- source / thread / output の catalog を追加する

まだやらないもの:

- raw source の変更
- binary attachment 本体 export
- fine-grained file diff export
- external DB dependency
- 複雑な差分アルゴリズム

## リスク

- fingerprint が粗いと、本当は変わっているのに unchanged 扱いする
- fingerprint が細かすぎると、毎回 changed になって差分更新の価値が落ちる
- UI が「全部取れた」ように見せると危険
- source root が消えた場合、前回 artifact をどう扱うかを明示しないと混乱する
- `state_5.sqlite` は便利だが、会話本文の正本ではない

## 推奨実装順

1. Inspection UI を先に強化する
2. Fidelity / source coverage を UI に出す
3. Catalog を追加する
4. `最新化` refresh run を追加する
5. changed / unchanged 判定を入れる
6. unchanged thread artifact reuse を入れる
7. current ZIP download を current artifact 参照にする

理由:

- UI が先にないと、差分更新が正しいかユーザーが判断できない
- catalog を先に作りすぎると、画面で検証できずブラックボックス化する
- full rebuild が残っていれば、差分更新に失敗しても逃げ道がある

## Master Checklist

凡例:

- `Impl`: 実装が完了しているか
- `Unit`: ユニットテストまたは worker / service level test があるか
- `E2E`: CLI / web / Docker Compose 経路で動作確認済みか
- `User`: Product Owner が画面や成果物を見て OK と判断したか

| ID | Item | Impl | Unit | E2E | User | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| UI-01 | Job Details に current thread / stage / elapsed / ETA を表示する | [x] | [ ] | [x] | [ ] | 既存 status fields を表示。web smoke で確認済み |
| UI-02 | Job Details に worker log tail を表示する | [x] | [ ] | [x] | [ ] | `logs/worker.log` を表示。web smoke で確認済み |
| UI-03 | Job Details に fidelity report summary を表示する | [x] | [ ] | [x] | [ ] | `fidelity_report.json` を UI 化。web smoke で確認済み |
| UI-04a | Job Details に source coverage / missing / limited を表示する | [x] | [ ] | [x] | [ ] | `fidelity_report.json` から表示。web smoke で確認済み |
| UI-04b | Job Details に degraded 判定を表示する | [x] | [ ] | [x] | [ ] | `update_manifest.json` を UI に出し、劣化 thread を表示。web smoke で確認済み |
| UI-05 | Thread Coverage 画面またはセクションを追加する | [x] | [ ] | [x] | [ ] | thread ごとの取得状況。web smoke で確認済み |
| UI-06 | Export Preview を UI から見られるようにする | [x] | [ ] | [x] | [ ] | readme / index / fidelity / ledger。web smoke で確認済み |
| UI-07 | Jobs 一覧の active panel を inspection 寄りに強化する | [x] | [ ] | [x] | [ ] | progress / current stage / elapsed / ETA / current thread。web smoke で確認済み |
| UI-08 | delete / download の確認 UI を modal 化する | [x] | [ ] | [x] | [ ] | Exports 一覧の削除 / ZIP 取得を modal 確認に変更。web smoke で回帰なしを確認済み |
| UI-09 | Jobs 一覧に current artifact dashboard を表示する | [x] | [ ] | [x] | [ ] | `current.json` を表示。web smoke で確認済み |
| UI-10 | Jobs 一覧に refresh history summary を表示する | [x] | [ ] | [x] | [ ] | `refresh-history.jsonl` の最新行を表示。web smoke で確認済み |
| CAT-01 | source file catalog を保存する | [x] | [x] | [x] | [ ] | run 単位の `catalog.json` に source path / size / mtime / hash を保存。worker unittest / web smoke で確認済み |
| CAT-02 | thread catalog を保存する | [x] | [x] | [x] | [ ] | run 単位の `catalog.json` に thread id / source refs / output hash を保存。worker unittest / web smoke で確認済み |
| CAT-03 | current artifact pointer を保存する | [x] | [x] | [x] | [ ] | `current.json` に最後に成功した full rebuild を保存。worker unittest / web smoke で確認済み |
| CAT-04 | refresh history を保存する | [x] | [x] | [x] | [ ] | `refresh-history.jsonl` に completed / failed run を追記。worker unittest / web smoke で確認済み |
| DIFF-01 | new / changed / unchanged / missing / degraded を判定する | [x] | [x] | [x] | [ ] | `update_manifest.json` に full rebuild 後の比較結果を保存。worker unittest / web smoke で確認済み |
| DIFF-02 | changed / new thread だけ再 parse する | [x] | [x] | [x] | [ ] | cache key が一致する unchanged thread は parse をスキップ。worker unittest / web smoke で確認済み |
| DIFF-03 | unchanged thread artifact を再利用する | [x] | [x] | [x] | [ ] | timeline / extracted JSON / observations を reuse。worker unittest / web smoke で確認済み |
| DIFF-04 | environment ledger を再構築する | [x] | [x] | [x] | [ ] | reused observations と新規 parse observations から全体再構築。worker unittest / web smoke で確認済み |
| EXP-01 | current full ZIP を再生成する | [x] | [x] | [x] | [ ] | full rebuild run の ZIP を `current.json` から参照。worker unittest / web smoke で確認済み |
| EXP-02 | readme / fidelity / ledger と UI の表示内容を揃える | [x] | [x] | [x] | [ ] | `Included / Known gaps` を worker 定数に寄せ、Overview / Exports / Details / readme.html の表現差を縮小。worker unittest / web smoke で確認済み |
| REF-01 | `最新化` ボタンを追加する | [x] | [ ] | [x] | [ ] | 現段階は full rebuild refresh run を開始。web smoke で確認済み |
| REF-02 | refresh run details を表示する | [x] | [ ] | [x] | [ ] | `update_manifest.json` の counts / processing mode / per-thread status を表示。web smoke で確認済み |
| REF-03 | refresh failure 時に previous current artifact を維持する | [x] | [x] | [x] | [ ] | success 時だけ `current.json` を更新。worker unittest / web smoke で確認済み |

## Review Gates

各 item は以下の順で進める。

1. `Impl`
2. `Unit`
3. `E2E`
4. `User`

`User` は Product Owner が実際の UI または生成 ZIP を確認して、期待に合うと判断したときだけ `[x]` にする。

## 最初に着手する候補

最初の実装候補は `UI-01`, `UI-02`, `UI-03`。

理由:

- catalog や差分更新より低リスク
- 既存成果物だけで実装できる
- ユーザーが「中身が見える」と感じる効果が大きい
- 後続の差分更新が正しいかを確認する土台になる
