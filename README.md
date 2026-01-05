# enex2md

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
  │       ├── _assets/              # 生成用アセット (JS)
  │       │   ├── crypto-js.min.js
  │       │   └── decrypt_note.js
  │       └── note_contents/        # ノート添付ファイル
  │           ├── image.png
  │           └── doc.pdf
  ├── OtherNotes/
  │   └── ...
```

## ライセンス

[LICENSE](LICENSE) を参照してください。