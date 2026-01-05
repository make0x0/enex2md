import argparse
import sys
import os
import yaml
import logging
import shutil
from pathlib import Path

# Suppress noisy third-party loggers BEFORE they are imported
for logger_name in ['weasyprint', 'fontTools', 'fontTools.subset', 'fontTools.ttLib', 'fontTools.ttLib.ttFont']:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.ERROR)
    logger.propagate = False

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

def process_enex(enex_path, config, converter, html_formatter, md_formatter=None, pdf_formatter=None):
    logging.info(f"Processing ENEX file: {enex_path}")
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    parser = NoteParser(enex_path)
    count = 0
    skipped = 0
    errors = 0
    
    # Get output root for checking existing PDFs
    base_output_root = Path(config.get('output', {}).get('root_dir', 'Converted_Notes'))
    enex_stem = Path(enex_path).stem
    
    # Number of parallel note workers (separate from OCR workers)
    # NOTE: Values > 1 cause OCR failures due to thread safety issues. Keep at 1.
    note_workers = config.get('processing', {}).get('note_workers', 1)
    
    def process_single_note(note_data):
        """Process a single note. Returns (success, skipped, title)"""
        title = note_data.get('title', 'Untitled')
        created = note_data.get('created')
        
        # Check if this note is already processed (PDF exists in _PDF folder)
        date_str = created.strftime(converter.date_format) if created else "NoDate"
        sanitized_title = converter._sanitize_filename(title)
        dir_name = f"{date_str}_{sanitized_title}"
        
        # Check for PDF in _PDF folder (with or without hash suffix)
        pdf_base_path = base_output_root / "_PDF" / enex_stem
        if pdf_base_path.exists():
            matching_folders = list(pdf_base_path.glob(f"{dir_name}*"))
            for folder in matching_folders:
                if folder.is_dir():
                    existing_pdfs = list(folder.glob("*.pdf"))
                    if existing_pdfs:
                        logging.debug(f"Skipping already processed: {title}")
                        return (False, True, title)  # Not converted, but skipped
        
        try:
            import threading
            worker_id = threading.current_thread().name.split('_')[-1]
            target_dir, intermediate_html, title, created, full_data = converter.convert_note(note_data)
            logging.info(f"[Note-W{worker_id}] Processing: {title} -> {target_dir}")
            
            # Generate HTML
            if 'html' in config['output']['formats']:
                html_formatter.generate(target_dir, intermediate_html, title, full_data)
            
            # Generate Markdown
            if md_formatter:
                md_formatter.generate(target_dir, intermediate_html, title, full_data)
                
            # Generate PDF
            if pdf_formatter:
                pdf_formatter.generate(target_dir, intermediate_html, title, full_data)
                
            return (True, False, title)  # Converted successfully
        except Exception as e:
            logging.error(f"Error converting note '{title}': {e}", exc_info=True)
            return (False, False, title)  # Error
    
    # Collect all notes first (needed for parallel processing)
    notes = list(parser.parse())
    logging.info(f"Found {len(notes)} notes in {enex_path}")
    
    # Process notes in parallel
    with ThreadPoolExecutor(max_workers=note_workers) as executor:
        futures = {executor.submit(process_single_note, note): note for note in notes}
        
        for future in as_completed(futures):
            success, was_skipped, title = future.result()
            if success:
                count += 1
            elif was_skipped:
                skipped += 1
            else:
                errors += 1
    
    if skipped > 0 or errors > 0:
        logging.info(f"Finished {enex_path}: {count} converted, {skipped} skipped, {errors} errors.")
    else:
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
    base_output_root = config.get('output', {}).get('root_dir', 'Converted_Notes')
    
    # Ensure base output dir exists for log file
    try:
        os.makedirs(base_output_root, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create output directory for logging: {e}")

    log_file_path = os.path.join(base_output_root, "enex2md.log")

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
    
    # Suppress noisy third-party loggers
    logging.getLogger('weasyprint').setLevel(logging.ERROR)
    logging.getLogger('fontTools').setLevel(logging.ERROR)
    logging.getLogger('fontTools.subset').setLevel(logging.ERROR)
    
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

    # Initialize formatters
    html_formatter = HtmlFormatter(config)
    
    md_formatter = None
    if 'markdown' in config.get('output', {}).get('formats', []):
        md_formatter = MarkdownFormatter(config)
        
    pdf_formatter = None
    if 'pdf' in config.get('output', {}).get('formats', []):
        try:
            from src.formatter_pdf import PdfFormatter
            pdf_formatter = PdfFormatter(config)
        except ImportError:
            logging.error("Failed to import PdfFormatter. Check dependencies.")

    for enex_file in enex_files:
        # Create a subfolder for this ENEX file
        enex_stem = Path(enex_file).stem
        output_root_for_enex = Path(base_output_root) / enex_stem
        
        converter = NoteConverter(output_root_for_enex, config)
        
        process_enex(enex_file, config, converter, html_formatter, md_formatter, pdf_formatter)

if __name__ == "__main__":
    main()
