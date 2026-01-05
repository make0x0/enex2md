import argparse
import sys
import os
import yaml
import logging
import shutil
from pathlib import Path

from src.parser import NoteParser
from src.converter import NoteConverter
from src.formatter_html import HtmlFormatter
from src.formatter_markdown import MarkdownFormatter

CONFIG_FILENAME = "config.yaml"

def load_config(config_path):
    if not os.path.exists(config_path):
        return {}
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def init_config():
    """Generates a default config.yaml in the current directory."""
    if os.path.exists(CONFIG_FILENAME):
        print(f"Error: {CONFIG_FILENAME} already exists.")
        sys.exit(1)
    
    default_config = """input:
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
  html_template: "" # 空の場合はデフォルトのシンプルなHTMLを使用
  embed_images: false # Markdownモードでは常にfalse扱い

markdown:
  # MarkdownファイルにYAML Front Matter（メタデータ）を付与するか
  add_front_matter: true
  # Markdown内の改行処理
  heading_style: "atx" # atx (# Heading) or setext (Heading\\n===)

logging:
  level: "INFO"
"""
    with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
        f.write(default_config)
    print(f"Created {CONFIG_FILENAME}. You can now edit it and run the tool.")

def process_enex(enex_path, config):
    logging.info(f"Processing ENEX file: {enex_path}")
    
    # Initialize components
    base_output_root = config.get('output', {}).get('root_dir', 'Converted_Notes')
    
    # Create a subfolder for this ENEX file
    enex_stem = Path(enex_path).stem
    output_root = Path(base_output_root) / enex_stem
    
    parser = NoteParser(enex_path)
    converter = NoteConverter(output_root, config)
    
    html_formatter = HtmlFormatter(config)
    md_formatter = MarkdownFormatter(config)
    
    formats = config.get('output', {}).get('formats', ['html'])
    
    count = 0
    for note_data in parser.parse():
        try:
            target_dir, intermediate_html, title, created, full_data = converter.convert_note(note_data)
            
            if 'html' in formats:
                html_formatter.generate(target_dir, intermediate_html, title, full_data)
                
            if 'markdown' in formats:
                md_formatter.generate(target_dir, intermediate_html, title, full_data)
            
            count += 1
        except Exception as e:
            logging.error(f"Error converting note '{note_data.get('title')}': {e}", exc_info=True)

    logging.info(f"Finished {enex_path}: {count} notes converted.")

def main():
    parser = argparse.ArgumentParser(description="Convert Evernote .enex files to HTML/Markdown.")
    parser.add_argument('path', nargs='?', help="File or directory path to process.")
    parser.add_argument('-r', '--recursive', action='store_true', help="Recursively search for .enex files.")
    parser.add_argument('-o', '--output', help="Output directory.")
    parser.add_argument('--format', help="Output format (html,markdown). Overrides config.")
    parser.add_argument('--init-config', action='store_true', help="Generate default configuration file.")

    args = parser.parse_args()

    # Handle init-config
    if args.init_config:
        init_config()
        sys.exit(0)

    # Load Config
    config = load_config(CONFIG_FILENAME)
    
    # Merge CLI args into config (simplified merging logic)
    if args.output:
        if 'output' not in config: config['output'] = {}
        config['output']['root_dir'] = args.output
    
    if args.format:
        if 'output' not in config: config['output'] = {}
        config['output']['formats'] = args.format.split(',')

    # Determine paths to process
    target_path = args.path or config.get('input', {}).get('default_path', '.')
    recursive = args.recursive or config.get('input', {}).get('default_recursive', False)

    # Determine Output directory base for logging
    output_root_base = config.get('output', {}).get('root_dir', 'Converted_Notes')
    
    # Ensure base output dir exists for log file
    try:
        os.makedirs(output_root_base, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create output directory for logging: {e}")

    log_file_path = os.path.join(output_root_base, "enex2md.log")

    # Setup Logging
    log_level = config.get('logging', {}).get('level', 'INFO')
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()), 
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file_path, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logging.info(f"Starting conversion. Target: {target_path}, Recursive: {recursive}")
    logging.info(f"Logging to file: {log_file_path}")
    
    # Check if target exists
    if not os.path.exists(target_path):
        logging.error(f"Path not found: {target_path}")
        sys.exit(1)

    # Collect files
    enex_files = []
    path_obj = Path(target_path)
    if path_obj.is_file():
        if path_obj.suffix.lower() == '.enex':
            enex_files.append(path_obj)
    elif path_obj.is_dir():
        pattern = '**/*.enex' if recursive else '*.enex'
        enex_files = list(path_obj.glob(pattern))

    if not enex_files:
        logging.warning("No .enex files found.")
        sys.exit(0)

    logging.info(f"Found {len(enex_files)} .enex files.")

    for enex_file in enex_files:
        process_enex(enex_file, config)

if __name__ == "__main__":
    main()
