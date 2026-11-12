# クラウド版Claude Code（claude.ai/code）で使う

PCに何も入れずに、ブラウザやスマホのClaudeアプリから、クラウド上でこのSkillを実行する手順です。

## 仕組み

- このリポジトリをクラウドセッションで開くと、`.claude/skills/verifying-sales-leads`（`skills/verifying-sales-leads` へのリンク）がプロジェクトのSkillとして読み込まれます。`claude --plugin-dir .` は不要です。
- クラウドのコンテナにはChromiumとPlaywrightが最初から入っています。`bootstrap.py` や `playwright install` は実行しません。
- PythonのライブラリはクラウドのEnvironment設定のセットアップスクリプトで準備します。

## 最初の1回だけの設定

claude.ai/code でEnvironmentを1つ作ります。既存のEnvironmentを編集してもかまいません。

1. **Network access**：**Full**（または同等の「すべて許可」）を選びます。調査先の企業サイトは毎回違うので、許可するドメインを事前に列挙できません。`Limited` のままだと企業サイトへの接続がすべて `403` で止まります。
2. **Environment variables**：

   ```text
   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers
   ```

3. **Setup script**：

   ```bash
   if [ -d verified-lead-research ]; then
     cd verified-lead-research
     python3 -m venv .venv
     .venv/bin/pip install -q -r skills/verifying-sales-leads/requirements.txt
   fi
   ```

4. このEnvironmentとリポジトリ `verified-lead-research` を選んで、新しいセッションを始めます。

## 使い方

セッションで `/verifying-sales-leads` を選ぶか、「日本産の業務用抹茶をアメリカへ売りたい。輸入会社の候補を公式サイトの証拠付きで探して」と依頼します。最初に、次のブラウザ診断が `"status": "ok"` になることを確認します。

```bash
.venv/bin/python skills/verifying-sales-leads/scripts/check_browser.py
```

## 注意

- クラウドのコンテナは一時的です。`runs/` は `.gitignore` の対象なので、コミットされません。セッションが終わる前に、`leads.xlsx`、`leads.csv`、`audit.json` をダウンロードしてください。Googleスプレッドシートへの書き出しも使えます。
- 大量モードの `research.sqlite3` も同じコンテナ内にあります。同じセッションを再開すれば続きから進めますが、新しいセッションには引き継がれません。
- 同じフォルダで `claude --plugin-dir .` も使うPCでは、Skillが2つ（プロジェクト用とPlugin用）表示されることがあります。どちらも同じ中身です。
