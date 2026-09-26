# WindowsでClaude Codeから使う

このページでは、はじめての人がWindowsで「証拠付き営業リスト」を使えるようになるまでを説明します。

最初の準備にはインターネット接続が必要です。Chromiumという確認用ブラウザもダウンロードするため、数分かかることがあります。

## 先に用意するもの

- Windows 10または11
- Claude Code
- Python 3
- Git、またはGitHubからダウンロードしたこのフォルダ
- インターネット接続

Pythonをインストールする時は、インストーラーの `Add python.exe to PATH` をオンにしてください。

## 1. フォルダを用意する

Gitを使う場合はPowerShellで次を実行します。

```powershell
git clone https://github.com/morioka1206/verified-lead-research.git
cd verified-lead-research
```

ZIPで受け取った場合は、まずZIPを展開します。展開した `verified-lead-research` フォルダをエクスプローラーで開き、上部のアドレス欄へ `powershell` と入力してEnterキーを押します。

## 2. Pythonとブラウザを準備する

開いたPowerShellへ、次を1行ずつ貼り付けます。

```powershell
py -3 -m venv .venv
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m pip install --requirement .\skills\verifying-sales-leads\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

英語の文字がたくさん表示されても、赤いエラーで止まらなければ問題ありません。

`py`が見つからない場合は、最初の行だけ次に変更します。

```powershell
python -m venv .venv
```

## 3. ブラウザをテストする

続けて次を実行します。

```powershell
.\.venv\Scripts\python.exe -m unittest tests\test_playwright_dynamic.py -v
```

成功すると最後に次のように表示されます。

```text
test_javascript_content_is_rendered ... ok

Ran 1 test
OK
```

ブラウザ画面が開かないのは正常です。Chromiumは裏側で起動し、JavaScriptで後から表示される文章を読み取ります。

## 4. Claude CodeでPluginを開く

同じPowerShellで次を実行します。

```powershell
claude --plugin-dir .
```

Claude Codeの入力欄で `/` を入力し、次のSkillを選びます。

```text
/verified-lead-research:verifying-sales-leads
```

見つからない場合はClaude Codeを終了し、リポジトリのフォルダで `claude --plugin-dir .` をもう一度実行します。

## 5. 最初の調査を頼む

次のように普通の日本語で入力します。

```text
日本産の業務用和牛をアメリカへ販売したいです。
輸入会社または卸会社を、公式サイトの証拠付きで5社探してください。
```

Claudeはいきなり会社を探さず、最初に条件を質問します。最後に表示される調査条件を確認してから、調査開始を選びます。

## 6. 結果を見る

結果は `runs\日時\` の中に保存されます。

- `leads.xlsx`：営業に使う全件の会社一覧。判定欄や確認メモはありません
- `leads.csv`：別のシステムへ渡しやすい日本語の会社データ
- `audit.json`：公式サイトの原文、証拠URL、判定理由を残した品質確認用の記録

まず `leads.xlsx` を開くと、営業に必要な会社名、公式URL、会社概要、公開連絡先などを確認できます。内容が怪しい時は、同じ会社を `audit.json` で確認します。

調査完了後、Claudeから品質チェックをするか質問されます。「10社だけ」を選ぶと、判断が難しい会社と代表的な会社を混ぜた確認表を作ります。GoogleスプレッドシートまたはExcelを選べます。Excelの場合は別ファイル `quality-review.xlsx` のB列で「正しい／間違い」を選び、必要ならC列へメモします。

問い合わせフォームは補助情報です。フォームだと明確に確認できない場合は、空欄でも問題ありません。会社の合否には使いません。

## 500社などの大量調査

51社以上を頼むと、大量調査モードを使います。たとえば500社の場合は、50候補ずつ次の順番で進みます。

1. 検索で見つけた候補を追加する
2. 50候補の公式サイトを確認する
3. 判定と証拠を `research.sqlite3` へ保存する
4. 同じ公式ドメインを除き、次の50候補へ進む
5. 合格500社、または設定した候補上限まで繰り返す

途中でClaude CodeやPCを閉じても、同じ `runs\日時\` フォルダから再開できます。500社を集める時は、最初の候補上限として2,500社をおすすめします。大量調査でも合格条件は変わらず、AIが対象企業として `accepted` と判断し、3種類の公式サイト証拠もそろった会社だけを `leads.csv` に入れます。

`research.sqlite3` はSkillが管理する途中記録です。ふだん人が開く必要はありません。営業には `leads.xlsx`、詳しい確認には `audit.json`、任意の抜き取り確認には `quality-review.xlsx` を使います。

## うまくいかない時

### Chromiumが見つからない

同じPowerShellで次を実行します。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m playwright install chromium
```

### 新しいPowerShellを開いた後にテストが失敗する

ブラウザの保存場所をもう一度設定してからテストします。

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m unittest tests\test_playwright_dynamic.py -v
```

### Skillが一覧に出ない

現在の場所が `verified-lead-research` フォルダであることを確認し、次で起動し直します。

```powershell
claude --plugin-dir .
```

### 更新したい

Gitで取得した場合は、リポジトリ内で次を実行します。

```powershell
git pull
$env:PLAYWRIGHT_BROWSERS_PATH = "$PWD\.playwright-browsers"
.\.venv\Scripts\python.exe -m pip install --requirement .\skills\verifying-sales-leads\requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

ZIPで受け取った場合は、新しいZIPを展開して新しいフォルダを使用します。

## Windowsで確認済みの内容

2026年9月25日に、Windows版Claude Codeで次を確認しました。

- Skillが起動し、選択式ヒアリングを実施できる
- 日本産和牛の米国向け候補を調査できる
- `leads.csv` と `audit.json` を出力できる
- 20候補を監査し、合格・対象外・確認待ち・取得不能を分けられる
- Chromiumを裏側で起動し、JavaScriptページを取得するテストが `OK` になる

検索結果はCodex版と完全に同じである必要はありません。会社を想像で補わず、AIの対象適合判定と公式サイトの3種類の証拠を両方使うことが共通ルールです。
