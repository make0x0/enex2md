import os
from pathlib import Path

class HtmlFormatter:
    def __init__(self, config):
        self.config = config
        self.template_path = config.get('content', {}).get('html_template')

    def generate(self, target_dir, intermediate_html, title, note_data):
        # We need to copy/link JS assets.
        # For simplicity, we assume they are copied to a specialized 'lib' folder in root output
        # or we just assume they are available relatively.
        # To make it fully self-contained per folder is safest but redundant.
        # Let's use a shared lib folder in the root output dir, and link to it with "../../lib/..."
        # Actually, SPEC says "成果物ディレクトリにライブラリのファイルを自動コピーする" (Copy lib files to artifact directory).
        # Let's assume there is a 'lib' folder at the root of 'Converted_Notes'.
        
        # Calculate relative path to lib root.
        # Structure is Root / Folder / NoteFolder / index.html
        # So we need to go up 2 levels.
        # Wait, structure is Root / Date_Title / index.html (flat per note) OR Root / Notebook / Note ?
        # SPEC says: Root / Folder (Category?? No, SPEC Example: Work/ProjectA/Date_Note)
        # The current implementation in Converter just puts it in OutputRoot / Date_Title directly because we don't track original notebooks yet in Parser.
        # Let's adhere to current simple structure: OutputRoot / Date_Title
        # So relative path to root is "../"
        
        # NOTE: If we want to support notebook folders, we need that info from Parser. 
        # Current Parser extracts tags, but not notebook name (which is not in .enex usually, unless we infer from filename or use a specific export).
        # SPEC says "Input: ./MyData/Work/ProjectA.enex" -> "Output: ./Converted/Work/ProjectA/..."
        # So we need to mirror input directory structure relative to input root.
        # This logic needs to be in the main loop or converter calling.
        # For this class, let's assume valid relative path is passed or we inject the script content directly?
        # Injecting content is safer for "single file" feel but crypto-js is big. "offline" usually implies local files.
        # Let's inject a script tag pointing to relative path.
        
        # Simplified: We will assume we put 'lib' in OutputRoot.
        # The Note is in OutputRoot/RelativeSubDir/NoteDir.
        # We need to compute 'depth' to find back to OutputRoot.
        
        # For now, let's write the HTML.
        
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  body {{ font-family: sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; }}
  .en-crypt-container {{ border: 1px solid #ccc; padding: 1em; background: #f9f9f9; margin: 1em 0; }}
  .en-crypt-content {{ display: none; margin-top: 1em; padding: 1em; border: 1px solid #ddd; background: #fff; }}
  .en-crypt-error {{ color: red; display: none; }}
</style>
<script src="crypto-js.min.js"></script>
<script src="decrypt_note.js"></script>
</head>
<body>
<h1>{title}</h1>
<div class="note-meta">
  <p>Created: {note_data.get('created')}</p>
  <p>Tags: {', '.join(note_data.get('tags', []))}</p>
</div>
<hr>
<div class="note-content">
{intermediate_html}
</div>
<script>
  // Auto-init decryption UI if needed
  document.addEventListener('DOMContentLoaded', function() {{
      initDecryption();
  }});
</script>
</body>
</html>"""
        
        output_path = target_dir / "index.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        input_assets_dir = Path("assets")
        system_assets_dir = Path("/opt/enex2md/assets")
        
        import shutil
        
        # Files to copy
        # We need crypto-js (external) and decrypt_note.js (internal/local)
        
        # 1. crypto-js.min.js
        src_local = input_assets_dir / "crypto-js.min.js"
        src_system = system_assets_dir / "crypto-js.min.js"
        dst = target_dir / "crypto-js.min.js"
        
        if src_local.exists():
             shutil.copy2(src_local, dst)
        elif src_system.exists():
             shutil.copy2(src_system, dst)
        else:
             logging.warning("crypto-js.min.js not found in assets/ or /opt/enex2md/assets/")

        # 2. decrypt_note.js (This is part of our code, so it should be in assets/ normally)
        src_local_decrypt = input_assets_dir / "decrypt_note.js"
        dst_decrypt = target_dir / "decrypt_note.js"
        if src_local_decrypt.exists():
             shutil.copy2(src_local_decrypt, dst_decrypt)
        else:
             logging.warning("decrypt_note.js not found in local assets/")

        return output_path

        return output_path
