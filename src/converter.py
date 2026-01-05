import os
import base64
import hashlib
import mimetypes
import logging
from pathlib import Path
from bs4 import BeautifulSoup
import re

# Placeholder for formatters
# from src.formatter_html import HtmlFormatter
# from src.formatter_markdown import MarkdownFormatter

class NoteConverter:
    def __init__(self, output_root, config):
        self.output_root = Path(output_root)
        self.config = config
        self.date_format = config.get('output', {}).get('date_format', '%Y-%m-%d')
        self.sanitize_char = config.get('output', {}).get('filename_sanitize_char', '_')
        self.formats = config.get('output', {}).get('formats', ['html'])

    def convert_note(self, note_data):
        title = note_data['title'] or "Untitled"
        created = note_data['created']
        
        # Create directory name
        date_str = created.strftime(self.date_format) if created else "NoDate"
        sanitized_title = self._sanitize_filename(title)
        dir_name = f"{date_str}_{sanitized_title}"
        target_dir = self.output_root / dir_name
        
        # Avoid duplicate dirs by indexing? (Simple version for now)
        if target_dir.exists():
             target_dir = self.output_root / f"{dir_name}_{hashlib.md5(title.encode()).hexdigest()[:4]}"

        target_dir.mkdir(parents=True, exist_ok=True)
        logging.info(f"Processing note: {title} -> {target_dir}")

        # Process Resources
        resource_map = self._process_resources(note_data['resources'], target_dir)
        
        # Convert Content
        if note_data['content']:
             intermediate_html = self._create_intermediate_html(note_data['content'], resource_map)
        else:
             intermediate_html = ""

        # Format Outputs
        # Ideally we load these classes dynamically or import them inside method to avoid circular deps if any
        # But for simplicity, we'll assume they are available or passed in.
        # For this step, I will just define the structure.
        
        return target_dir, intermediate_html, title, created, note_data

    def _sanitize_filename(self, name):
        """Sanitize string to be safe for filenames."""
        return re.sub(r'[<>:"/\\|?*]', self.sanitize_char, name).strip()

    def _process_resources(self, resources, target_dir):
        """Decodes and saves resources. Returns a map of hash -> filename."""
        res_map = {}
        for res in resources:
            if not res['data_b64']:
                continue
            
            try:
                data = base64.b64decode(res['data_b64'])
                md5_hash = hashlib.md5(data).hexdigest()
                
                # Determine filename
                filename = res['filename']
                if not filename:
                    ext = mimetypes.guess_extension(res['mime']) or '.dat'
                    filename = f"{md5_hash}{ext}"
                
                # Check for collision or just overwrite
                file_path = target_dir / filename
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                res_map[md5_hash] = filename
                
            except Exception as e:
                logging.error(f"Failed to process resource: {e}")
        
        return res_map

    def _create_intermediate_html(self, enml_content, resource_map):
        """Parses ENML and transforms <en-media> and others."""
        soup = BeautifulSoup(enml_content, 'xml') # ENML is XML
        
        # Handle en-media
        for media in soup.find_all('en-media'):
            media_hash = media.get('hash')
            if media_hash in resource_map:
                filename = resource_map[media_hash]
                mime = media.get('type', '')
                
                if mime.startswith('image/'):
                    new_tag = soup.new_tag('img', src=filename, alt=filename)
                else:
                    new_tag = soup.new_tag('a', href=filename)
                    new_tag.string = filename
                
                media.replace_with(new_tag)
        
        # Handle en-todo
        for todo in soup.find_all('en-todo'):
            is_checked = todo.get('checked') == 'true'
            new_tag = soup.new_tag('input', type='checkbox')
            if is_checked:
                new_tag['checked'] = 'checked'
            # Checkboxes inside MD often need specific spacing, but for HTML it's fine.
            # Markdownify usually handles input type=checkbox.
            todo.replace_with(new_tag)

        # Handle en-crypt
        for crypt in soup.find_all('en-crypt'):
            hint = crypt.get('hint', '')
            cipher_text = crypt.get_text()
            
            # Create a placeholder div for HTML decryption
            # The formatter will style this, but we structure it here
            wrapper = soup.new_tag('div', **{'class': 'en-crypt-container', 'data-hint': hint, 'data-cipher': cipher_text})
            # Add some fallback text for non-JS or MD
            fallback = soup.new_tag('span', **{'class': 'en-crypt-fallback'})
            fallback.string = "**[Encrypted Content]**"
            wrapper.append(fallback)
            
            crypt.replace_with(wrapper)

        # Extract whatever is inside <en-note> (the root of ENML)
        en_note = soup.find('en-note')
        if en_note:
            # We want the inner HTML of en-note
            # decode_contents() does this
             return en_note.decode_contents()
        
        return str(soup)
