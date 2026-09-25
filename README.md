# 証拠付き営業リスト

海外へ商品やサービスを売りたい人のために、**実在する会社を公式サイトの証拠付きで探すSkill**です。

抹茶や和牛などの食品に限らず、機械、化粧品、日用品、素材、法人向けサービスなどでも、商材・市場・営業目的を変えて使えます。

詳しい説明は、ブラウザで [GUIDE.html](GUIDE.html) を開いてください。

## 何ができるの？

最初に選択式のヒアリングで、次の条件を一緒に決めます。

- 何を売りたいか
- どの国・地域へ売りたいか
- 輸入会社、卸会社、販売店、ホテル、工場など、誰とつながりたいか
- 現地事業所を必須にするか、現地販売や配送実績でもよいか
- 入れたくない会社と必要な件数

条件が固まったら、候補企業の公式サイトを確認して次を作ります。

- `leads.csv`：会社名、公式URL、公開メール、日本語概要、人の確認欄
- `audit.json`：全候補の判定、公式サイトの原文証拠、証拠URL、確認日時

### 少量と大量、どちらにも対応

- 標準モード：合格5〜50社を一度に調査
- 大量モード：50候補ずつ処理し、合格500社などの大きな依頼を途中保存しながら継続

大量モードは `runs/<日時>/research.sqlite3` に進み具合を保存します。CodexやClaude Codeを閉じても、次回は未完了のバッチから再開できます。候補は全バッチを通して公式ドメイン単位で重複除去されます。

## 普通のAIリストと何が違うの？

普通のAIへ「アメリカの抹茶卸会社を30社」と頼むだけでは、AIの記憶や推測から、存在しない会社名・古いURL・推測メールが混ざることがあります。

このSkillは次の順で確認します。

1. Web検索で候補を見つける
2. 公式サイトを実際に取得する
3. 「商材」「会社の役割」「対象市場での活動」の3種類の証拠を探す
4. 証拠文が取得ページに本当にあるか、プログラムでもう一度確かめる
5. 3種類すべてがそろった会社だけを合格にする

分からない会社は無理に合格にせず、`review` または `blocked` にします。会社名、URL、メールアドレスを想像で補いません。

## インストール

### Mac（かんたん）

### 先に用意するもの

- Mac
- CodexまたはClaude Code。両方でも大丈夫です
- インターネット接続
- Python 3

Pythonが入っているか分からなくても、インストーラーが確認して案内します。

### 手順

1. 受け取った `verified-lead-research` フォルダを開きます。
2. 中にある **`INSTALL.command`** をダブルクリックします。
3. 黒い画面が開いたら、そのまま待ちます。必要なブラウザ部品も自動で準備します。
4. 「インストールが完了しました」と表示されたら、Enterキーを押します。
5. CodexまたはClaude Codeをいったん閉じ、もう一度開きます。

Macに止められた場合は、`INSTALL.command` を右クリックして「開く」を選び、もう一度「開く」を選んでください。

### Windows + Claude Code

Windowsでは、PowerShellからClaude Code Pluginとして起動します。Python環境とChromiumを最初の1回だけ準備します。

詳しい画面ごとの手順は [Windows版Claude Codeセットアップ](docs/windows-claude-code.md) を参照してください。基本のコマンドは次のとおりです。

```powershell
cd "C:\保存した場所\verified-lead-research"
py -3 -m venv .venv
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m pip install --requirement .\skills\verifying-sales-leads\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
claude --plugin-dir .
```

Claude Codeが開いたら、`/verified-lead-research:verifying-sales-leads` を選び、売りたい商材と対象国を伝えます。

## 最初の使い方

新しい会話で、たとえば次のように依頼します。

> 日本産の業務用抹茶をアメリカへ売りたいです。輸入会社と卸会社の候補を、公式サイトの証拠付きで探してください。

Skillがいきなり検索を始めることはありません。選択式の質問で条件を整理し、最後に調査条件を一枚で見せます。そこで「この条件で調査を開始」を選ぶと検索が始まります。

別の例：

- 和牛をヨーロッパへ販売するため、食肉輸入会社を探す
- 包装機械を東南アジアへ販売するため、販売代理店を探す
- 日本の化粧品原料を韓国へ販売するため、メーカーと卸会社を探す
- 法人向けサービスの現地パートナー候補を探す

## 大事な注意

- 公式サイトで確認できる公開情報だけを扱います。
- 問い合わせフォームは補助情報です。通常の確認中にフォームだと明確に分かった場合だけ保存し、見つからなくても会社の合否には影響しません。
- フォーム送信、営業メール送信、CAPTCHA回避は行いません。
- 公式サイトを確認できても、法人登記まで証明したことにはなりません。
- 対象サイトや通信状態によって、目標件数に届かないことがあります。その場合も合格条件はゆるめません。
- 大量モードでも1社最大5ページと3証拠の合格条件は変わりません。

## 大量調査の例

500社を依頼した場合、既定では最大2,500候補を50候補ずつ処理します。

```text
500社を依頼
  ↓
50候補を調査して途中保存
  ↓
全バッチ共通で重複を除去
  ↓
次の50候補を調査
  ↓
合格500社または候補上限まで繰り返す
```

各バッチの完了後に `leads.csv`、`audit.json`、`summary.json` が更新されます。候補上限まで確認しても目標に届かない場合は、品質を下げずに不足数を報告します。

## うまくいかない時

### `python3 が見つかりません` と出る

[Python公式サイト](https://www.python.org/downloads/macos/)からPython 3をインストールし、もう一度 `INSTALL.command` を開きます。

### CodexやClaude CodeでSkillが見つからない

アプリを完全に終了してから開き直し、新しい会話で試してください。

### インストールをやり直したい

同じ `INSTALL.command` をもう一度開けば、安全に更新されます。自分で作った同名フォルダがある場合は、上書きせず停止します。

### Windowsでブラウザが動くか確認したい

PowerShellでリポジトリへ移動し、次を実行します。画面を出さずにChromiumを起動し、JavaScriptで表示される文章を取得できれば `OK` と表示されます。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m unittest tests\test_playwright_dynamic.py -v
```

## 手動インストール（詳しい人向け）

```bash
cd /受け取った場所/verified-lead-research
python3 skills/verifying-sales-leads/scripts/bootstrap.py
.venv/bin/python skills/verifying-sales-leads/scripts/install_skill.py
```

Claude CodeでPluginとして直接試す場合：

```bash
claude --plugin-dir /受け取った場所/verified-lead-research
```

## 開発・確認

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Windowsでの確認：

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

調査結果は `runs/<日時>/` に保存され、Gitには追加されません。設計判断は `docs/`、現在地は `STATUS.md` にあります。
