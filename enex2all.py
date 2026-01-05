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
  # 指定可能な値: "html", "markdown", "pdf"
  formats: ["html", "markdown", "pdf"]

content:
  html_template: "" # 空の場合はデフォルトのシンプルなHTMLを使用
  embed_images: false # Markdownモードでは常にfalse扱い

markdown:
  # MarkdownファイルにYAML Front Matter（メタデータ）を付与するか
  add_front_matter: true
  # Markdown内の改行処理
  heading_style: "atx" # atx (# Heading) or setext (Heading\\n===)

ocr:
  enabled: true
  language: "jpn"
  workers: 2

processing:
  note_workers: 1 # ノート並列数（※WeasyPrintの競合回避のため1推奨）

logging:
  level: "INFO"
"""
    with open(CONFIG_FILENAME, 'w', encoding='utf-8') as f:
        f.write(default_config)
    print(f"Created {CONFIG_FILENAME}. You can now edit it and run the tool.")

    # --- Rich Progress Implementation ---
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn
    from rich.logging import RichHandler
    from rich.console import Console
    
    console = Console()
    
    # 1. Setup Rich Logging
    # Remove existing handlers if any (basicConfig might not have run yet if we override here, 
    # but main() usually sets it up. We will override main's setup or modify main.)
    # Actually, we should move basicConfig setup to here or rely on main passing us a configured logger?
    # No, enex2all.py is a script. Let's modify main() primarily.
    # This block is inside legacy process_enex which is not ideal for the "Global" progress bar user wants.
    # We should refactor process_enex to accept a progress task.
    
    # ... Skipping partial refactor here. 
    # I will replace the WHOLE content of main() and process_enex() and helper functions 
    # to support the new architecture properly.
    
    # Let's count notes first (Helper function)
    
def count_notes_in_enex(enex_path):
    """Fast scan to count <note> tags."""
    count = 0
    try:
        with open(enex_path, 'rb') as f:
            for line in f:
                if b'<note>' in line: # Simple heuristic
                    count += 1
    except Exception as e:
        logging.warning(f"Failed to count notes in {enex_path}: {e}")
    return count

def process_enex(enex_path, config, converter, html_formatter, md_formatter, pdf_formatter, progress=None, task_id=None):
    logging.info(f"Processing ENEX file: {enex_path}")
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    parser = NoteParser(enex_path)
    count = 0
    skipped = 0
    errors = 0
    
    base_output_root = Path(config.get('output', {}).get('root_dir', 'Converted_Notes'))
    enex_stem = Path(enex_path).stem
    note_workers = config.get('processing', {}).get('note_workers', 1)
    
    def process_single_note(note_data):
        try:
            nonlocal count, skipped, errors
            title = note_data.get('title', 'Untitled')
            created = note_data.get('created')
            
            # --- Check Resume (Reuse Logic) ---
            date_str = created.strftime(converter.date_format) if created else "NoDate"
            sanitized_title = converter._sanitize_filename(title)
            
            pdf_base_path = base_output_root / "_PDF" / enex_stem
            if pdf_base_path.exists():
                pdf_filename = f"{sanitized_title}.pdf"
                potential_pdf = pdf_base_path / pdf_filename
                prefixed_pdf_filename = f"{date_str}_{sanitized_title}.pdf"
                potential_prefixed_pdf = pdf_base_path / prefixed_pdf_filename
                
                if potential_pdf.exists() or potential_prefixed_pdf.exists():
                     # logging.debug(f"Skipping already processed: {title}")
                     return (False, True, title)

            # --- Conversion ---
            import threading
            worker_id = threading.current_thread().name.split('_')[-1]
            target_dir, intermediate_html, title, created, full_data = converter.convert_note(note_data)
            logging.info(f"[Note-W{worker_id}] Processing: {title}")
            
            if 'html' in config['output']['formats']:
                html_formatter.generate(target_dir, intermediate_html, title, full_data)
            
            if md_formatter:
                md_formatter.generate(target_dir, intermediate_html, title, full_data)
                
            if pdf_formatter:
                pdf_formatter.generate(target_dir, intermediate_html, title, full_data)
                
            return (True, False, title)
            
        except Exception as e:
            logging.error(f"Error converting note '{title}': {e}", exc_info=False) # Reduce noise
            return (False, False, title)

    # Collect notes
    notes = list(parser.parse())
    # logging.info(f"Found {len(notes)} notes in {enex_path}") # Duplicate with progress bar info
    
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
            
            # Update Progress
            if progress and task_id is not None:
                progress.advance(task_id)

    logging.info(f"Finished {enex_path}: {count} converted, {skipped} skipped, {errors} errors.")

def main():
    parser = argparse.ArgumentParser(description="Convert Evernote .enex files to HTML/Markdown.")
    parser.add_argument('path', nargs='?', help="File or directory path to process.")
    parser.add_argument('-r', '--recursive', action='store_true', help="Recursively search for .enex files.")
    parser.add_argument('-o', '--output', help="Output directory.")
    parser.add_argument('--format', help="Output format (html,markdown). Overrides config.")
    parser.add_argument('--init-config', action='store_true', help="Generate default configuration file.")
    parser.add_argument('--skip-scan', action='store_true', help="Skip pre-scanning files for note count (fast mode).")

    args = parser.parse_args()

    # Handle init-config
    if args.init_config:
        init_config()
        sys.exit(0)

    # Load Config
    config = load_config(CONFIG_FILENAME)
    
    # Merge CLI args
    if args.output:
        if 'output' not in config: config['output'] = {}
        config['output']['root_dir'] = args.output
    
    if args.format:
        if 'output' not in config: config['output'] = {}
        config['output']['formats'] = args.format.split(',')

    # Paths
    target_path = args.path or config.get('input', {}).get('default_path', '.')
    recursive = args.recursive or config.get('input', {}).get('default_recursive', False)
    skip_scan = args.skip_scan or config.get('processing', {}).get('skip_scan', False)
    base_output_root = config.get('output', {}).get('root_dir', 'Converted_Notes')
    
    try:
        os.makedirs(base_output_root, exist_ok=True)
    except Exception as e:
        print(f"Warning: Could not create output directory: {e}")

    log_file_path = os.path.join(base_output_root, "enex2md.log")

    # --- Rich Setup ---
    from rich.logging import RichHandler
    from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeRemainingColumn, MofNCompleteColumn
    from rich.console import Console
    
    console = Console()
    
    # Configure root logger to file AND RichHandler (console)
    log_level = config.get('logging', {}).get('level', 'INFO')
    
    # File Handler (Full logs)
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    
    # Rich Handler (Console logs, pretty)
    rich_handler = RichHandler(console=console, show_time=False, show_path=False)
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        handlers=[file_handler, rich_handler],
        force=True # Override any previous config
    )
    
    # Suppress noisy third-party loggers
    logging.getLogger('weasyprint').setLevel(logging.ERROR)
    logging.getLogger('fontTools').setLevel(logging.ERROR)
    
    logging.info(f"Starting conversion. Target: {target_path}")
    
    # Check target
    if not os.path.exists(target_path):
        logging.error(f"Path not found: {target_path}")
        sys.exit(1)

    # Collect .enex files
    enex_files = []
    path_obj = Path(target_path)
    if path_obj.is_file() and path_obj.suffix.lower() == '.enex':
        enex_files.append(path_obj)
    elif path_obj.is_dir():
        pattern = '**/*.enex' if recursive else '*.enex'
        enex_files = list(path_obj.glob(pattern))

    if not enex_files:
        logging.warning("No .enex files found.")
        sys.exit(0)

    # --- Pre-scan count ---
    total_notes = None 
    if not skip_scan:
        with console.status("[bold green]Scanning files to count notes...") as status:
            total_notes = 0
            enex_counts = {}
            for i, ef in enumerate(enex_files, 1):
                status.update(f"[bold green]Scanning file {i}/{len(enex_files)}: {ef.name} (Found {total_notes} notes so far)...")
                c = count_notes_in_enex(ef)
                enex_counts[ef] = c
                total_notes += c
            console.print(f"[bold]Found {len(enex_files)} files with {total_notes} total notes.[/bold]")
    else:
        logging.info("Skipping pre-scan (Fast Mode). Progress bar will be indeterminate.")

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
            logging.error("Failed to import PdfFormatter.")

    # --- Main Process Loop with Progress Bar ---
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
        transient=False  # Keep bar after completion
    ) as progress:
        
        main_task = progress.add_task(f"[green]Total Progress (Notebook 0/{len(enex_files)})", total=total_notes)
        
        for i, enex_file in enumerate(enex_files, 1):
            # Update description with current file index
            progress.update(main_task, description=f"[green]Total Progress (Notebook {i}/{len(enex_files)})")
            
            # Create a subfolder for this ENEX file
            enex_stem = Path(enex_file).stem
            output_root_for_enex = Path(base_output_root) / enex_stem
            
            converter = NoteConverter(output_root_for_enex, config)
            
            # Pass progress and task to process_enex
            # Note: process_enex logic is now simplified above
            process_enex(enex_file, config, converter, html_formatter, md_formatter, pdf_formatter, progress, main_task)

if __name__ == "__main__":
    main()
