Windows 利用者向けの正面玄関は PowerShell wrapper とし、その先で Docker Compose を実行する。
WSL / host shell は自動テスト・開発検証の裏口として残し、通常手順には出しすぎない。
ホスト上の直接 Python / Node 実行はデフォルトで停止し、例外は明示的な `ALLOW_HOST_RUN` 系 env を設定した場合に限る。
