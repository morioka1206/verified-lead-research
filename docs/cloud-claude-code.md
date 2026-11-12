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

## モデルの使い分け

Claude Codeでは、会話のモデル（Opusなど）が条件のヒアリングと最終確認を担当し、量の多い作業を軽いモデルの補助エージェントへ任せます。

- `lead-scout`（Haiku）：検索して候補企業のURLを集めます。合否は判断しません。
- `lead-assessor`（Sonnet）：取得した公式サイトを読み、証拠と判定を書きます。複数を並行で動かします。

補助エージェントが書いた証拠も、これまでどおりプログラムが原文と照合します。軽いモデルの判断が甘くても、証拠がそろわない会社は合格になりません。詳しい流れは `skills/verifying-sales-leads/references/model-delegation.md` にあります。PCの `claude --plugin-dir .` でも同じエージェントが使えます。

## 米国以外の国を調べるとき

Claude Codeに組み込まれた検索は米国向けの結果しか返しません。ほかの国では次を使います。

- 精肉店・飲食店・カフェなど店舗型の相手：OpenStreetMapから取り込みます（`import_osm.py --preset butcher --preset steak-restaurant --area DE-BY` など）。相手の種類ごとの組み合わせ（プリセット）が用意されています。本家のサーバーがクラウドからの接続を切る場合は、自動で公開ミラーに切り替えます。混雑で取れなかった州は、同じコマンドをもう一度実行すると、その州だけ取り直します。
- 輸入・卸会社など地図に載りにくい相手：国を指定できるBrave Search API（`search_web.py --country DE --lang de`）を使います。BraveのAPIキーが必要です。クラウドでは、Claudeが出す入力欄から `api.search.brave.com` 用の秘密情報として保存すると、キーが会話に表示されずに使われます。

## 注意

- クラウドのプロキシはHTTPSだけを通します。`http://` のサイトは自動で `https://` に切り替えて取得し、それでも開けない場合は「httpのみのサイト」と記録します。

- クラウドではホスト名を手元で名前解決できないため、名前解決できない時だけDNS-over-HTTPS（Cloudflare）でアドレスを調べ、公開アドレスかどうかを従来どおり確認します。調査先のホスト名がCloudflareのDNSに送られます。

- クラウドのコンテナは一時的です。`runs/` は `.gitignore` の対象なので、コミットされません。セッションが終わる前に、`leads.xlsx`、`leads.csv`、`audit.json` をダウンロードしてください。Googleスプレッドシートへの書き出しも使えます。
- 大量モードの `research.sqlite3` も同じコンテナ内にあります。同じセッションを再開すれば続きから進めますが、新しいセッションには引き継がれません。
- 同じフォルダで `claude --plugin-dir .` も使うPCでは、Skillが2つ（プロジェクト用とPlugin用）表示されることがあります。どちらも同じ中身です。
