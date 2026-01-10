import argparse
import sys
import os
import yaml
import logging
import shutil
import json
from lxml import etree
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError

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
    """Fast scan to count <note> tags using streaming XML parser."""
    count = 0
    try:
        # iterparse is efficient and streaming
        # tag='note' event='end' ensures we count complete notes
        context = etree.iterparse(str(enex_path), events=('end',), tag='note', recover=True, huge_tree=True)
        for event, elem in context:
            count += 1
            # Clear element to save memory during scan
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
        del context
    except Exception as e:
        logging.warning(f"Failed to count notes in {enex_path}: {e}")
    return count

def process_enex(enex_path, config, converter, html_formatter, md_formatter, pdf_formatter, progress=None, task_id=None, args=None):
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
            logging.error(f"Error converting note '{title}': {e}", exc_info=True) # Full traceback for debugging
            return (False, False, title)

    # --- Retry Filter Logic (load before streaming) ---
    retry_entries = None
    if getattr(args, 'retry_run', None):
        try:
            with open(args.retry_run, 'r', encoding='utf-8') as f:
                retry_data = json.load(f)
            # Build a set of (enex_name, title) tuples for matching
            retry_entries = set()
            for entry in retry_data:
                if isinstance(entry, dict):
                    retry_entries.add((entry.get('enex_name', ''), entry.get('title', '')))
                else:
                    # Fallback for old format (just titles)
                    retry_entries.add(('', entry))
            logging.info(f"Retry Run: Loaded {len(retry_entries)} failed notes from {args.retry_run}")
        except Exception as e:
            logging.error(f"Failed to load retry file: {e}")
            return

    # --- Processing (Sequential Streaming - memory efficient) ---
    failed_notes_log = []
    timeout_sec = getattr(args, 'timeout', 60) if args else 60
    import time
    import signal
    
    # Simple timeout using alarm (Unix only, but works in Docker)
    class TimeoutException(BaseException):
        pass
    
    def timeout_handler(signum, frame):
        raise TimeoutException("Note processing timed out")
    
    # Process notes sequentially from generator (memory efficient)
    # Error handling wrapped around the generator iteration
    try:
        for note_data in parser.parse():
            title = note_data.get('title', 'Untitled')
            
            # Check retry filter
            if retry_entries is not None:
                if (enex_stem, title) not in retry_entries and ('', title) not in retry_entries:
                    skipped += 1
                    if progress and task_id is not None:
                        progress.advance(task_id)
                    continue
            
            # Process with timeout
            start_time = time.time()
            try:
                # Set alarm for timeout (Unix signal-based)
                old_handler = signal.signal(signal.SIGALRM, timeout_handler)
                signal.alarm(timeout_sec)
                
                try:
                    success, was_skipped, result_title = process_single_note(note_data)
                    signal.alarm(0)  # Cancel alarm
                    
                    if success:
                        count += 1
                    elif was_skipped:
                        skipped += 1
                    else:
                        errors += 1
                        failed_notes_log.append({
                            "enex_file": str(enex_path),
                            "enex_name": enex_stem,
                            "title": result_title,
                            "reason": "error"
                        })
                except TimeoutException:
                    elapsed = int(time.time() - start_time)
                    logging.error(f"TIMEOUT: '{title}' exceeded {timeout_sec}s (elapsed: {elapsed}s). Skipping.")
                    errors += 1
                    failed_notes_log.append({
                        "enex_file": str(enex_path),
                        "enex_name": enex_stem,
                        "title": title,
                        "reason": f"timeout ({elapsed}s)"
                    })
                finally:
                    signal.signal(signal.SIGALRM, old_handler)
                    signal.alarm(0)
                    
            except Exception as e:
                logging.error(f"Exception processing note '{title}': {e}")
                errors += 1
                failed_notes_log.append({
                    "enex_file": str(enex_path),
                    "enex_name": enex_stem,
                    "title": title,
                    "reason": str(e)
                })
            
            # Update Progress
            if progress and task_id is not None:
                progress.advance(task_id)
                
    except Exception as e:
        # XML parse error or other generator error
        logging.error(f"Failed to parse ENEX file '{enex_path}': {e}")
        logging.error(f"Remaining notes in this ENEX file will be skipped.")
        # Record failure for the file
        output_root = config.get('output', {}).get('root_dir', '/output')
        fail_log_path = os.path.join(output_root, args.fail_log if args else 'failed_notes.json')
        failed_notes_log.append({
            "enex_file": str(enex_path),
            "enex_name": enex_stem,
            "title": "(PARSE ERROR - REMAINING NOTES SKIPPED)",
            "reason": str(e)
        })

    # Write Fail Log
    if failed_notes_log:
        try:
            # Write to output directory so it's accessible outside Docker
            output_root = config.get('output', {}).get('root_dir', '/output')
            fail_log_path = os.path.join(output_root, args.fail_log if args else 'failed_notes.json')
            
            # Append to existing if retrying
            existing_failures = []
            if os.path.exists(fail_log_path):
                with open(fail_log_path, 'r', encoding='utf-8') as f:
                    try: existing_failures = json.load(f)
                    except: pass
            
            # Dedupe by (enex_name, title) key
            seen_keys = set()
            combined = []
            for entry in existing_failures + failed_notes_log:
                if isinstance(entry, dict):
                    key = (entry.get('enex_name', ''), entry.get('title', ''))
                else:
                    key = ('', entry)
                if key not in seen_keys:
                    seen_keys.add(key)
                    combined.append(entry)
            
            with open(fail_log_path, 'w', encoding='utf-8') as f:
                json.dump(combined, f, ensure_ascii=False, indent=2)
            logging.info(f"Recorded {len(failed_notes_log)} failures to {fail_log_path}")
        except Exception as e:
            logging.error(f"Failed to write fail logs: {e}")

    logging.info(f"Finished {enex_path}: {count} converted, {skipped} skipped, {errors} errors.")

def main():
    parser = argparse.ArgumentParser(description="Convert Evernote .enex files to HTML/Markdown.")
    parser.add_argument('path', nargs='?', help="File or directory path to process.")
    parser.add_argument('-r', '--recursive', action='store_true', help="Recursively search for .enex files.")
    parser.add_argument('-o', '--output', help="Output directory.")
    parser.add_argument('--format', help="Output format (html,markdown). Overrides config.")
    parser.add_argument('--init-config', action='store_true', help="Generate default configuration file.")
    parser.add_argument('--skip-scan', action='store_true', help="Skip pre-scanning files for note count (fast mode).")
    parser.add_argument('--pdf-fit-mode', action='store_true', help="Force content to fit within PDF page width (breaks tables/pre).")
    parser.add_argument('--retry-run', help="JSON file containing list of note titles to retry.")
    parser.add_argument('--fail-log', default="failed_notes.json", help="Output JSON file for failed/skipped notes.")
    parser.add_argument('--timeout', type=int, default=360, help="Timeout in seconds for processing a single note.")

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
    
    if args.pdf_fit_mode:
        if 'pdf' not in config: config['pdf'] = {}
        config['pdf']['fit_mode'] = True

    base_output_root = config.get('output', {}).get('root_dir', 'Converted_Notes')
    # Sync authoritative root path back to config for formatters
    if 'output' not in config: config['output'] = {}
    config['output']['root_dir'] = str(base_output_root)
    
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
        
        target_root_dir = Path(target_path) if Path(target_path).is_dir() else Path(target_path).parent

        for i, enex_file in enumerate(enex_files, 1):
            # Update description with current file index
            progress.update(main_task, description=f"[green]Total Progress (Notebook {i}/{len(enex_files)})")
            
            # Create a subfolder for this ENEX file, preserving directory structure if recursive
            enex_stem = Path(enex_file).stem
            try:
                # Calculate relative path from input root
                rel_path = enex_file.parent.relative_to(target_root_dir)
            except ValueError:
                rel_path = Path(".")
            
            output_root_for_enex = Path(base_output_root) / rel_path / enex_stem
            
            converter = NoteConverter(output_root_for_enex, config)
            
            # Pass progress and task to process_enex
            # Note: process_enex logic is now simplified above
            process_enex(enex_file, config, converter, html_formatter, md_formatter, pdf_formatter, progress, main_task, args)

if __name__ == "__main__":
    main()
