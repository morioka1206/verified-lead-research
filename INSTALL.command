#!/bin/zsh
set -eu

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"
LOG_FILE="$PROJECT_DIR/install.log"
: > "$LOG_FILE"

echo ""
echo "証拠付き営業リストを準備します。"
echo "この画面は、終わるまで閉じないでください。"
echo ""

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 が見つかりませんでした。"
  echo "https://www.python.org/downloads/macos/ からインストールしてください。"
  echo ""
  read "?Enterキーを押すと閉じます。"
  exit 1
fi

echo "[1/2] 必要な部品を準備しています…"
if ! python3 skills/verifying-sales-leads/scripts/bootstrap.py >> "$LOG_FILE" 2>&1; then
  echo "準備の途中で問題が起きました。"
  echo "同じフォルダの install.log を、配布した人へ送ってください。"
  read "?Enterキーを押すと閉じます。"
  exit 1
fi

echo ""
echo "[2/2] CodexとClaude Codeから使えるようにしています…"
if ! .venv/bin/python skills/verifying-sales-leads/scripts/install_skill.py >> "$LOG_FILE" 2>&1; then
  echo "インストールの途中で問題が起きました。"
  echo "同じフォルダの install.log を、配布した人へ送ってください。"
  read "?Enterキーを押すと閉じます。"
  exit 1
fi

echo ""
echo "インストールが完了しました。"
echo "CodexまたはClaude Codeを開き直し、新しい会話で使ってください。"
echo ""
read "?Enterキーを押すと閉じます。"
