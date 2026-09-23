# Verified Lead Research

特定の商材を海外へ販売するために、実在性と適合性を根拠付きで確認した企業リストを作成するプロジェクトです。

現在地をやさしい言葉で確認する場合は `STATUS.md` を参照してください。

## 目標

- AIに会社名やURLを推測させない
- 候補企業の公式サイトを実際に取得して確認する
- 会社名、公式URL、根拠URL、根拠文を必須にする
- 公開メールを取得し、問い合わせフォームは通常確認中に明確に見つかった場合だけ補助情報として保存する
- 不明な情報は推測せず `null` または `unknown` とする
- 商材、対象地域、営業目的、理想顧客像をキャンペーンごとに変更できるようにする

## 開発方針

最初にCodexとClaudeの両方で利用できるポータブルなSkillとして、小規模な調査フローを検証します。人手で評価したデータから判定基準を調整し、十分な精度を確認できた後にCloudflare上のアプリケーションへ拡張します。

1. Skillプロトタイプ
2. 評価用データセットと精度測定
3. Cloudflareアプリケーション
4. 複数AIプロバイダーと外部データソースへの対応

## ディレクトリ

- `docs/`: 要件、設計、意思決定
- `skill/verifying-sales-leads/`: Codex・Claude共通のSkill本体
- `src/`: 将来のアプリケーション実装
- `tests/`: 判定ルールと抽出処理のテスト

## セットアップと確認

```bash
python3 skill/verifying-sales-leads/scripts/bootstrap.py
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python skill/verifying-sales-leads/scripts/install_skill.py
```

Skillの正本は `skill/verifying-sales-leads/` です。インストーラーはCodexへ安全な通常コピーを置き、Claude Codeへ正本のシンボリックリンクを置きます。取得結果は `runs/<日時>/` に保存し、Gitには追加しません。

調査時の詳しい順序、キャンペーン入力、AIから判定スクリプトへの受け渡しは、Skill本体と `references/` を参照してください。

## 現在の状態

Skill v1の道具本体は実装済みです。APIやクラウドサービスの契約は必要ありません。PlaywrightとChromiumはローカルへインストールします。抹茶・アメリカの実験では37候補を公式サイトで確認し、証拠が3種類そろった30社を出力しました。人による公式URL確認では30社すべてが正しいと判定され、精度100%で目標の90%を達成しました。米国に事業所があること自体は必須条件ではなく、米国向け販売・配送・顧客・倉庫などの活動証拠を対象地域の根拠としています。

Skillの共通部分は標準的な `SKILL.md`、`references/`、`scripts/` に限定します。`agents/openai.yaml` はCodex向けの任意メタデータであり、調査ロジックは含めません。
