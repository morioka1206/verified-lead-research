# Skill互換性方針

## 共通本体

`skills/verifying-sales-leads/` を唯一の正本とします。調査フロー、証拠要件、スキーマ、実行スクリプトには特定のモデル名やベンダー固有APIを埋め込みません。

CodexとClaudeはいずれも、YAML frontmatterを持つ `SKILL.md` と、必要に応じて読み込む参照ファイル・実行スクリプトという構造を利用できます。

公式資料：

- OpenAI: https://developers.openai.com/plugins/build/plugins
- Claude Code: https://code.claude.com/docs/en/plugins

## プラットフォーム固有部分

- Codex向けUI情報は `agents/openai.yaml` に置く
- Claude固有の設定が将来必要になった場合も、共通 `SKILL.md` には混ぜず薄い設定ファイルとして分離する
- ブラウザ、検索、ファイル出力は利用環境が提供するツールを選ぶ
- 特定ツールがない場合は、その項目を `unknown` または `blocked` として扱う

## インストール

このリポジトリ内のSkillを正本にします。`scripts/install_skill.py` は、Codexには管理用印を付けた通常コピーを作り、Claude Codeにはシンボリックリンクを作ります。CodexのサンドボックスはSkillの書き込み先にシンボリックリンクが含まれる構成を拒否するためです。

再実行時、Codex側はこのスクリプトが作ったコピーだけを更新します。無関係な既存フォルダやリンクは上書きせず停止します。Claude側のリンクは正本を直接参照します。どちらの場合も、編集する場所はリポジトリ内の正本です。

Codexで先にテストし、その後Claude Codeで同じキャンペーン、クロール、評価スキーマを確認します。クライアントのWeb検索結果は完全一致を要求しません。

## 実機確認

2026年9月25日にWindows版Claude Codeで、Pluginの読み込み、選択式ヒアリング、和牛卸候補の調査、日本語CSVと監査JSONの出力を確認しました。監査JSONでは20候補を `accepted`、`review`、`rejected`、`blocked` に分け、合格会社に商材・会社の役割・対象市場の3証拠と原文が保存されていました。

同じWindows環境でPlaywright 1.63.0のChromiumをヘッドレス起動し、JavaScriptで生成した文章を取得する単体テストが合格しました。Windowsの詳しい準備方法は [windows-claude-code.md](windows-claude-code.md) に記載します。

配布版v1.1では、51社以上の依頼を50候補ずつ進める大量調査モードを追加しました。途中経過はPython標準機能のSQLiteへ保存するため、追加のデータベース製品は不要です。CodexとClaude Code、macOSとWindowsで同じキャンペーン設定と保存形式を使います。500社の依頼では候補上限2,500社を初期提案とし、公式ドメインの重複を除きながら再開できます。

## 他の人へ渡すPlugin版

現在のリポジトリには共通Skillに加え、CodexとClaude Code向けの配布用Pluginマニフェストがあります。調査ロジックは複製せず、次の外箱を同じGitリポジトリへ置きます。

```text
plugin-root/
├── plugin.json                    OpenAIのポータブルPlugin用
├── .codex-plugin/plugin.json      Codex互換用
├── .claude-plugin/plugin.json     Claude Code用
└── skills/
    └── verifying-sales-leads/
        ├── SKILL.md
        ├── references/
        └── scripts/
```

Skill本体は共有できますが、OpenAIとClaude Codeのマーケットプレイスは別です。一方へ公開しただけで、もう一方へ自動公開されるとは扱いません。Claude Codeは開発時に `claude --plugin-dir <plugin-root>` でローカルPluginを読み込めます。

## AI APIとの関係

対話型のSkill検証は、そのクライアントで利用可能なモデルとツールを使います。Cloudflareアプリから自動実行する段階では、ChatGPTやClaudeのサブスクリプションではなく、選択したAIプロバイダーのAPI契約または別の実行基盤が必要です。
