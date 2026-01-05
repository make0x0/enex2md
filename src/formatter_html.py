import os
import shutil
import logging
from pathlib import Path
from bs4 import BeautifulSoup

class HtmlFormatter:
    def __init__(self, config):
        self.config = config
        self.crypto_js_filename = "crypto-js.min.js"
        self.decrypt_js_filename = "decrypt_note.js"
        
        # Load template
        template_path = config.get('content', {}).get('html_template')
        if template_path and os.path.exists(template_path):
             with open(template_path, 'r', encoding='utf-8') as f:
                 self.template = f.read()
        else:
             self.template = self._get_default_template()

    def generate(self, target_dir, intermediate_html, title, note_data):
        """Generates index.html and copies necessary assets."""
        
        # Prepare assets directory
        assets_dir = target_dir / "_assets"
        assets_dir.mkdir(exist_ok=True)
        
        # Copy assets to _assets/
        self._copy_asset(self.crypto_js_filename, assets_dir / self.crypto_js_filename)
        self._copy_asset(self.decrypt_js_filename, assets_dir / self.decrypt_js_filename)
        
        # Parse template
        soup = BeautifulSoup(self.template, 'html.parser')
        
        # Set Title
        if soup.title:
            soup.title.string = title
        
        # Insert Meta
        meta_div = soup.find('div', class_='note-meta')
        if meta_div:
            # Clear existing dummy content
            meta_div.clear()
            
            created_p = soup.new_tag('p')
            created_p.string = f"Created: {note_data.get('created', '')}"
            meta_div.append(created_p)
            
            tags = note_data.get('tags', [])
            if tags:
                tags_p = soup.new_tag('p')
                tags_p.string = f"Tags: {', '.join(tags)}"
                meta_div.append(tags_p)
                
            source_url = note_data.get('source_url')
            if source_url:
                url_p = soup.new_tag('p')
                url_a = soup.new_tag('a', href=source_url)
                url_a.string = "Source URL"
                url_p.append(url_a)
                meta_div.append(url_p)

        # Update Heading
        h1 = soup.find('h1')
        if h1:
            h1.string = title

        # Add Script Tags pointing to _assets/
        body = soup.body
        if body:
            s1 = soup.new_tag("script", src="_assets/crypto-js.min.js")
            body.append(s1)
            s2 = soup.new_tag("script", src="_assets/decrypt_note.js")
            body.append(s2)
            
            # Add auto-init script
            s_init = soup.new_tag("script")
            s_init.string = "document.addEventListener('DOMContentLoaded', function() { initDecryption(); });"
            body.append(s_init)

        # Insert Content
        content_div = soup.find('div', class_='note-content')
        if not content_div:
            # Fallback if class not found, try id
            content_div = soup.find(id='note-content')
        
        if content_div:
            content_div.clear()
            # Parse intermediate HTML to insert safely
            content_soup = BeautifulSoup(intermediate_html, 'html.parser')
            content_div.append(content_soup)
        
        output_path = target_dir / "index.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
        return output_path

    def _copy_asset(self, filename, dest_path):
        """Copies an asset file from local assets or system assets to destination."""
        input_assets_dir = Path("assets")
        system_assets_dir = Path("/opt/enex2md/assets")
        
        src_local = input_assets_dir / filename
        src_system = system_assets_dir / filename
        
        try:
            if src_local.exists():
                shutil.copy2(src_local, dest_path)
            elif src_system.exists():
                shutil.copy2(src_system, dest_path)
            else:
                logging.warning(f"Asset not found: {filename} (checked {src_local} and {src_system})")
        except Exception as e:
            logging.error(f"Failed to copy asset {filename}: {e}")

    def _get_default_template(self):
        return """<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Note Title</title>
<style>
  body { font-family: sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; }
  .en-crypt-container { border: 1px solid #ccc; padding: 1em; background: #f9f9f9; margin: 1em 0; }
  .en-crypt-content { display: none; margin-top: 1em; padding: 1em; border: 1px solid #ddd; background: #fff; }
  .en-crypt-error { color: red; display: none; }
  img { max-width: 100%; height: auto; }
</style>
</head>
<body>
<h1>Note Title</h1>
<div class="note-meta">
  <p>Created: ...</p>
  <p>Tags: ...</p>
</div>
<hr>
<div class="note-content" id="note-content">
</div>
</body>
</html>"""
