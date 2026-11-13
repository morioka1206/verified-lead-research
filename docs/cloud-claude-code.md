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

検索の届く範囲は、クラウド／PC、接続する検索ツール、設定によって変わる可能性があります。「US-only」という表示や米国に偏った結果があっても、それだけで「Claude Codeは米国外の会社を検索できない」とは判断しません。利用可能な地域の制約と、検索結果の対象国も区別します。

調査の最初に対象国の現地語で少数の検索を試し、現地企業の公式サイトが見つかるか確認します。環境と確認日を記録し、結果が偏る場合や大量の候補が必要な場合は次を補助に使います。Codexでも同じ選び方にし、検索範囲を無制限とは説明しません。

- 精肉店・飲食店・カフェなど店舗型の相手：OpenStreetMapから取り込みます（`import_osm.py --preset butcher --preset steak-restaurant --area DE-BY` など）。相手の種類ごとの組み合わせ（プリセット）が用意されています。本家のサーバーがクラウドからの接続を切る場合は、自動で公開ミラーに切り替えます。混雑で取れなかった州は、同じコマンドをもう一度実行すると、その州だけ取り直します。
- 輸入・卸会社など地図に載りにくい相手：組み込み検索で不足する場合は、国を指定できるBrave Search API（`search_web.py --country DE --lang de`）を選べます。BraveのAPIキーが必要です。外部APIを使わない方針なら勝手に切り替えず、組み込み検索・公開業界名簿で進め、不足を説明します。クラウドの秘密情報保存に対応している場合は、`api.search.brave.com` 用の秘密情報として保存します。キーを会話へ貼り付ける必要はありません。

参考：[Claude Codeの検索ツール仕様](https://code.claude.com/docs/en/tools-reference#websearch-tool-behavior)、[Codexの検索仕様](https://learn.chatgpt.com/docs/web-search)。仕様や環境は変わるため、実際のセッションでの確認を優先します。

## 注意

- クラウドのプロキシはHTTPSだけを通します。`http://` のサイトは自動で `https://` に切り替えて取得し、それでも開けない場合は「httpのみのサイト」と記録します。

- クラウドではホスト名を手元で名前解決できないため、名前解決できない時だけDNS-over-HTTPS（Cloudflare）でアドレスを調べ、公開アドレスかどうかを従来どおり確認します。調査先のホスト名がCloudflareのDNSに送られます。

- クラウドのコンテナは一時的です。`runs/` は `.gitignore` の対象なので、コミットされません。セッションが終わる前に、`leads.xlsx`、`leads.csv`、`audit.json` をダウンロードしてください。Googleスプレッドシートへの書き出しも使えます。
- 大量モードの `research.sqlite3` も同じコンテナ内にあります。同じセッションを再開すれば続きから進めますが、新しいセッションには引き継がれません。
- 同じフォルダで `claude --plugin-dir .` も使うPCでは、Skillが2つ（プロジェクト用とPlugin用）表示されることがあります。どちらも同じ中身です。
