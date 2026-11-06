# Public Manual Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 既存の説明を承認済みデザインに統合し、マニュアルだけをGitHub Pagesで公開する。

**Architecture:** `GUIDE.html` を唯一のHTML更新元とする。公開用の小さな標準Pythonビルダーがそのファイルだけを `index.html` にコピーし、GitHub Actionsは専用成果物だけをPagesへ送る。調査用プログラムとは独立した変更とする。

**Tech Stack:** HTML、CSS、ブラウザ標準JavaScript、Python標準ライブラリ、unittest、GitHub Actions / Pages。

**Spec:** `docs/superpowers/specs/2026-11-06-public-manual-design.md`

## Global Constraints

- `GUIDE.html` を唯一の更新元とし、同じ内容をGitHub Pagesに公開する。
- 公開するのはマニュアルだけ。調査データ、連絡先、ログ、台帳を公開しない。
- Skill本体の調査処理や合格条件は変更しない。
- Claude Codeの導入を中心に、Mac／Windowsの手順を説明する。Codexの案内も残す。
- 白・アイボリー・深緑、控えめな文字サイズ、編集的な余白を採用する。
- 既存の無関係な変更をコミットに含めない。

## Review Focus

- ローカルHTMLとPagesではリンクの基準が変わる。配布・参照リンクは公開先でも有効であること。
- OS切り替えで別のタブ群まで変わらないこと。キーボードとJavaScript無効時にも必要な案内が読めること。
- クリップボードが拒否されても、手動コピーの案内と原文が残ること。
- 調査データやシンボリックリンクが作業フォルダにあっても、公開成果物へ入らないこと。
- Windowsの実行手順や次回起動を、Mac専用インストーラーと混同しないこと。

---

### Task 1: GUIDE.htmlの統合

**Files:** Modify `GUIDE.html`; Create `tests/test_manual.py`.

**Interfaces:** Consumes existing guide, approved preview, actual bootstrap/install/browser scripts and plugin manifests. Produces self-contained Japanese HTML with existing anchors `about`, `benefits`, `difference`, `install`, `start`, `scale`, `output`, `limits`, `faq`.

- [ ] 実際のインストール処理と公式Claude Codeドキュメントを確認し、初回準備・ローカルPlugin起動・個人用Skill登録を整理する。
- [ ] `test_manual.py` にunittestを追加する。全目次アンカーが存在、IDが一意、各タブのパネルが存在、Mac／Windows／Codexの案内と既存9節が存在、ローカル絶対パス・私的連絡先・誤認を招く精度保証が含まれないことを検査する。
- [ ] `python3 -m unittest tests.test_manual -v` を実行し、新しい案内構造への期待が既存HTMLでは失敗することを確認する。
- [ ] 承認済みプレビューの雰囲気を `GUIDE.html` へ反映し、旧版の内容を省略せず再編集する。導入の前提、入手、フォルダを開く、準備、ブラウザ診断、起動、Skill呼び出し、成功確認、次回起動、更新を分ける。安全警告の回避を勧めない。
- [ ] タブはグループ単位でクリックと矢印キーに対応。JS無効では両OSの内容を読めるようにする。コピー失敗時には手動選択を案内する。外部依存は追加しない。
- [ ] 同テストを再実行し全件成功を確認する。

### Task 2: マニュアル限定の公開処理

**Files:** Create `scripts/build_public_manual.py`, `.github/workflows/publish-manual.yml`; Extend `tests/test_manual.py`.

**Interfaces:** `build(source: Path, destination: Path) -> Path` creates a previously nonexistent destination, copies only `source` as `index.html`, returns that path. CLI: `python3 scripts/build_public_manual.py --output <new-directory>`. Source is repository `GUIDE.html`; workflow supplies a dedicated runner temporary directory.

- [ ] テストを追加する。原文と公開HTMLのバイト一致、成果物が `index.html` だけ、隣の `runs/audit.json` と `.env` が非公開、既存の出力先・ソースのsymlinkを拒否、任意の私的ファイルへ置換できないCLIを検査する。
- [ ] テストを実行しビルダー未実装による失敗を確認する。
- [ ] 標準ライブラリだけでビルダーを実装する。既存ディレクトリは削除・上書きせず拒否する。
- [ ] GitHub公式手順を確認してActionsを作成する。公開変更・手動実行で作動し、テスト→専用成果物作成→artifact upload→Pages deployを行う。公開権限はデプロイjobに限定し、リポジトリ全体をアップロードしない。
- [ ] ビルダーのテストと実ビルドを実行し、公開ファイル一覧が `index.html` のみであることを確認する。

### Task 3: 画面確認・記録・公開

**Files:** Modify `README.md`, `STATUS.md`; Update this plan's completed checkboxes.

**Interfaces:** Consumes Tasks 1–2; produces verified deployment URL, installation guidance and truthful status record.

- [ ] ブラウザでPC幅とスマートフォン相当の表示を確認する。目次、OS切り替え、キーボード、コピー成功／拒否の案内、長いコマンド、JS無効時の可読性を確認する。
- [ ] ページ内リンク、公開先の参照リンク、GitHubのZIP取得リンクを検査する。READMEは公開ガイドとローカルHTMLの両方を案内する。
- [ ] `python3 -m unittest discover -s tests -v` を実行し結果を記録する。既存の無関係なテスト変更を手元で含む場合は、その点を区別する。
- [ ] マニュアル関連ファイルだけをステージし差分を確認してコミットする。STATUSには公開準備と既存調査データ非公開を平易に記録する。
- [ ] GitHubの認証・Pages設定・公開対象を読み取り確認する。許可済み範囲でpushしPagesを設定する。認証・権限等で止まった場合は正確な状況と残る操作を報告する。
- [ ] Actions成功と公開URLの実際の応答・表示を確認する。成功前に公開完了と報告しない。公開後の記録更新が必要なら小さな追補コミットを行う。
