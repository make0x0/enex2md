# ENEX to HTML/Markdown Converter 仕様書

## 1. 概要

Evernoteからエクスポートされた `.enex` ファイルを読み込み、ノート単位でフォルダを分割してHTML、Markdown、および添付ファイルとして出力するPythonスクリプトの仕様。
ノート作成日をフォルダ名に付与し、時系列での管理を容易にする。
複数のENEXファイルの一括処理、ディレクトリ階層の維持、Docker実行環境の提供に加え、出力フォーマット（HTML/Markdown）を選択可能とする。

## 2. システム要件

- **言語**: Python 3.10+
- **コンテナ環境**: Docker
- **推奨ライブラリ**:
    - **XML解析**: `lxml` または `xml.etree.ElementTree`
    - **HTML生成/操作**: `BeautifulSoup4`
    - **Markdown変換**: `markdownify` (推奨) または同等の HTML to Markdown 変換ライブラリ
    - **設定ファイル**: `PyYAML`
    - **CLI引数解析**: `argparse`
    - **パス操作**: `pathlib`, `glob`, `os.path`
    - **その他**: `base64`, `hashlib`, `mimetypes`, `logging`

## 3. 入出力定義

### 3.1 入力

**コマンドライン引数:**

- **パス指定**: ファイルまたはディレクトリ（複数可）。
- **再帰オプション**: `-r` / `--recursive`
- **出力先指定**: `-o` / `--output`
- **フォーマット指定（オプション）**: `--format html,markdown` (設定ファイルを上書き)

### 3.2 出力構造

指定されたルート配下に階層構造を維持して出力する。
設定に応じて `index.html` と `content.md` のいずれか、または両方を生成する。

**例:**
*設定: HTMLとMarkdownの両方を出力*
*入力: `./MyData/Work/ProjectA.enex`*

**出力結果:**
```text
./Converted/
  ├── Work/
  │   └── ProjectA/
  │       ├── 2023-01-01_会議議事録/
  │       │   ├── index.html                # HTML版ノート
  │       │   ├── content.md                # Markdown版ノート
  │       │   ├── image001.png              # 添付画像（両方から参照される）
  │       │   └── doc.pdf                   # 添付書類
  │       └── ProjectA_conversion.log
```

## 4. 設定ファイル仕様 (config.yaml)

出力形式を選択するための `output_formats` を追加。

```yaml
input:
  default_path: "."
  default_recursive: false

output:
  root_dir: "./Converted_Notes"
  date_format: "%Y-%m-%d"
  filename_sanitize_char: "_"
  
  # 出力フォーマットのリスト
  # 指定可能な値: "html", "markdown"
  # 両方出力する場合: ["html", "markdown"]
  formats: ["html", "markdown"]

content:
  html_template: "./template.html"
  embed_images: false # Markdownモードでは常にfalse扱い（ファイル参照）となる

markdown:
  # MarkdownファイルにYAML Front Matter（メタデータ）を付与するか
  add_front_matter: true
  # Markdown内の改行処理（バックスラッシュをエスケープするか等）
  heading_style: "atx" # atx (# Heading) or setext (Heading\n===)

logging:
  level: "INFO"
```

## 5. 詳細処理ロジック

### 5.1 メインフロー
（既存仕様と同様。ファイル収集 -> ベースパス計算 -> ループ処理）

### 5.2 ENEXファイル単位の処理
（既存仕様と同様。出力先計算 -> ログ設定 -> XML解析）

### 5.3 ノートごとの処理ステップ

#### Step 1: メタデータ抽出
Title, Created Date, Updated Date, Tags, Author, Source URL 等を取得。

#### Step 2: ノートフォルダ作成
フォルダ名: `target_dir / f"{date_str}_{sanitized_title}"` を作成。

#### Step 3: リソース抽出・保存
`<resource>` タグ解析 -> Base64デコード -> MD5ハッシュ計算 -> ファイル保存。
`dict_hash_to_filename` マッピングを作成。

**Markdown特有の考慮**: Markdownは埋め込み（Base64）を標準サポートしないため、必ずファイルとして保存する。

#### Step 4: 本文変換（フォーマット分岐）
`<content>` 内の ENML をパースし、まず「中間HTML（Intermediate HTML）」を作成する。

**中間HTML作成**:
`<en-media>` タグを検索し、Step 3 のマッピングを用いて適切なタグに置換する。
- 画像 (`type="image/..."`): `<img src="./image.png" alt="image.png">`
- その他: `<a href="./doc.pdf">doc.pdf</a>`
- Evernote固有タグ (`<en-todo checked="true"/>` 等) を `<input type="checkbox" checked>` 等に置換。

**HTML出力処理** (`output.formats` に `"html"` が含まれる場合):
1. 中間HTMLをテンプレートに埋め込む。
2. `index.html` として保存。

**Markdown出力処理** (`output.formats` に `"markdown"` が含まれる場合):
1. **変換**: 中間HTMLを `markdownify` 等のライブラリに渡し、Markdownテキストに変換する。
2. **リンクの再現**: ライブラリが `<img>` タグを `![alt](src)` に、`<a>` タグを `[text](href)` に変換することを確認する。
3. **YAML Front Matter付与**:
   `markdown.add_front_matter` が `true` の場合、ファイルの先頭にメタデータを付与する。
   ```yaml
   ---
   title: 会議議事録
   created: 2023-01-01
   tags: [仕事, ミーティング]
   source_url: https://...
   ---
   ```
4. **保存**: `content.md` として保存。
5. **エラーハンドリング**: 変換中に例外が発生した場合（複雑なネスト構造など）、エラーログに記録し、生のHTMLをコードブロックとしてMarkdown内にダンプする等のフォールバック処理を行う（`raw_html` オプション等）。

## 6. テンプレート要件

### HTML用
（既存仕様と同様。シンプルなHTML5）

### Markdown用
テンプレートファイルは使用せず、変換ライブラリの出力とFront Matterの結合によって生成する。

## 7. エラーハンドリング

### Markdown変換失敗
HTML構造が複雑すぎてMarkdownに綺麗に変換できない場合、ログに `WARNING` を出力する。
完全に変換不能な箇所は、可能な限りテキスト情報を残すか、元のHTMLタグを残す設定とする。

### ログ出力
HTMLとMarkdownそれぞれの成功/失敗をログに記録する。
例: `[INFO] Converted HTML: Success, Markdown: Success -> ./path/to/folder`

## 8. 成果物とドキュメンテーション要件

- **Pythonスクリプト**: `enex2all.py`
- **requirements.txt**: `markdownify` を追加。
- **Docker環境**: 変更なし（Pythonイメージにライブラリ追加のみ）。
- **README.md**:
    - Markdown出力の設定方法を追記。
    - Front Matterの活用方法（Obsidian等での利用）に言及。

## 9. 参考情報: ENML to Markdown 変換の注意点
実装者向けの技術的留意事項。

### 9.1 `<en-todo>` の処理
Evernoteのチェックボックス `<en-todo checked="true"/>` は、Markdownのチェックリスト記法 `- [x]` に変換されるべきである。
中間HTML作成段階で `<input type="checkbox">` に置換しておけば、多くのMarkdown変換ライブラリがこれを認識する。

### 9.2 テーブルの処理
Evernoteのノートにはテーブルが頻出する。Markdownのテーブル表現能力はHTMLより低いため（セル結合ができない等）、複雑なテーブルは崩れる可能性がある。
ライブラリの設定で「テーブル変換を試みるが、無理ならHTMLタグのまま残す」オプションがあれば検討すること。

### 9.3 画像リンクの整合性
Markdownファイル（`content.md`）と画像ファイルは同じフォルダに配置されるため、リンクパスは相対パス `./image.png` または単に `image.png` となる。これにより、フォルダごと移動してもリンク切れしなくなる。