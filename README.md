# (全部途中!!)enex2md

Evernote のエクスポートファイル (.enex) を Markdown や HTML に変換するツールです。

## 特徴

- **複数フォーマット対応**: HTML または Markdown (あるいはその両方) への変換をサポート。
- **添付ファイル保持**: 画像やPDFなどの添付ファイルを抽出し、ノートと同じフォルダに保存します。
- **Docker対応**: 環境構築の手間なく、Dockerコンテナとして即座に実行可能です。
- **暗号化ノート対応 (HTMLのみ)**: Evernoteの暗号化されたテキスト (`<en-crypt>`) を、ブラウザ上でパスワード入力により復号して閲覧できます。

## 必要要件

- Docker

## 使い方

### 1. 準備

まず、このリポジトリをクローンし、Dockerイメージをビルドします。

```bash
git clone https://github.com/your-repo/enex2md.git
cd enex2md
docker compose build
```

### 2. 設定ファイルの生成

初回実行時は、設定ファイルのテンプレート (`config.yaml`) を生成します。

```bash
docker compose run --rm app --init-config
```

カレントディレクトリに `config.yaml` が作成されます。必要に応じて編集してください（出力先フォルダやフォーマットなど）。

### 3. 変換の実行

`.enex` ファイルを指定して変換を実行します。

**単一ファイルの変換:**
```bash
docker compose run --rm app path/to/MyNotes.enex
```

**ディレクトリ内のファイルを再帰的に変換:**
```bash
docker compose run --rm app -r path/to/EnexFolder
```

**CLIオプションによる上書き:**
```bash
# 出力先を ./my_output に変更し、Markdown形式のみ出力する場合
docker compose run --rm app path/to/note.enex -o ./my_output --format markdown
```

### 外部ディレクトリのファイルを変換する場合（推奨）

ホスト側の「入力フォルダ」と「出力フォルダ」の両方をDockerコンテナにマウントすることで、任意の場所のファイルを処理し、任意の場所に保存できます。
わかりやすくするために、コンテナ内ではそれぞれ `/input`, `/output` という固定パスにマウントすることをお勧めします。

**コマンド例:**
```bash
docker compose run --rm \
  -v "/Users/user-name/ev-backup-work/enex_dir":/input \
  -v "/Users/user-name/ev-backup-work/output_dir/en-output":/output \
  app -r /input -o /output
```

**解説:**
1. `-v "ホストの入力パス":/input`: 入力データをコンテナの `/input` にマウント。
2. `-v "ホストの出力パス":/output`: 出力先をコンテナの `/output` にマウント。
3. アプリ引数: `-r /input` で入力を、`-o /output` で出力を指定。

この方法であれば、コンテナ内部の複雑なパスを気にせずに利用できます。

## 出力構造

設定された出力ディレクトリ（デフォルト: `Converted_Notes`）配下に、以下のように出力されます。

```text
Converted_Notes/
  ├── MyNotes/                      # ENEXファイル名に基づくフォルダ
  │   └── 2023-01-01_会議議事録/
  │       ├── index.html            # HTML版 (ブラウザ閲覧用)
  │       ├── content.md            # Markdown版 (Obsidian等用)
  │       ├── 会議議事録.pdf         # PDF版 (検索可能)
  │       ├── _assets/              # 生成用アセット (JS)
  │       │   ├── crypto-js.min.js
  │       │   └── decrypt_note.js
  │       └── note_contents/        # ノート添付ファイル
  │           ├── image.png
  │           ├── image.png.xml     # OCR認識データ
  │           ├── image.png.ocr.json  # OCR位置情報
  │           └── doc.pdf
  ├── OtherNotes/
  │   └── ...
  └── _PDF/                         # PDFのみのクリーンフォルダ
      └── MyNotes/
          └── 2023-01-01_会議議事録/
              └── 会議議事録.pdf
```

## 設定オプション (config.yaml)

`--init-config` で生成される `config.yaml` には以下のオプションがあります:

### 基本設定

```yaml
input:
  default_path: "."           # デフォルトの入力パス
  default_recursive: false    # デフォルトで再帰検索するか

output:
  root_dir: "./Converted_Notes"   # 出力ルートディレクトリ
  date_format: "%Y-%m-%d"         # ファイル名の日付フォーマット
  filename_sanitize_char: "_"     # ファイル名禁止文字の置換文字
  formats: ["html", "markdown", "pdf"]  # 出力フォーマット

content:
  embed_images: false   # 画像をBase64埋め込み (HTMLのみ)

markdown:
  add_front_matter: true    # YAML Front Matter を追加
  heading_style: "atx"      # 見出しスタイル (atx or setext)
```

### OCR設定

画像からテキストを抽出し、PDF内で検索可能にします。

```yaml
ocr:
  enabled: true      # OCRを有効化
  language: "jpn"    # Tesseract言語 (jpn, eng, jpn+eng など)
  workers: 2         # OCR並列処理のワーカー数 (推奨: 2-4)
```

### 並列処理設定

```yaml
processing:
  note_workers: 1    # ノート並列処理のワーカー数 (デフォルト: 1)
```

> [!WARNING]
> `note_workers` を増やすと処理速度が向上しますが、WeasyPrintやTesseractのリソース競合によりOCRエラーが発生する可能性があります。エラーが頻発する場合は **1** に戻してください。

### ログ設定

```yaml
logging:
  level: "INFO"   # ログレベル (DEBUG, INFO, WARNING, ERROR)
```

ログには処理を行っているワーカーIDが表示されます：
- `[Note-W*]`: ノート変換プロセス
- `[Ocr-W*]`: OCR処理スレッド

## 機能

### OCR (光学文字認識)

- 画像からテキストを抽出（Tesseract使用）
- 位置情報付きOCR：PDF内で検索すると正確な位置がハイライトされます
- Evernoteの認識データがない場合に自動でOCR実行

### PDF出力

- 各ノートをPDFとして出力
- 背景色・ハイライトを保持
- OCRテキストを透明レイヤーとして埋め込み（検索可能）
- `_PDF/` フォルダにクリーンなコピーを作成

### 処理再開機能

処理が中断しても、再実行すると完了済みのノート（`_PDF/` にPDFが存在するもの）は自動的にスキップされます。

## ライセンス

[LICENSE](LICENSE) を参照してください。