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

        # Create subdirectories
        contents_dir = target_dir / "note_contents"
        contents_dir.mkdir(exist_ok=True)

        # Process Resources
        # Pass contents_dir instead of target_dir
        resource_map = self._process_resources(note_data['resources'], contents_dir)
        
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
            if not res.get('data_b64'): # Use .get() for safety
                continue
            
            try:
                data = base64.b64decode(res['data_b64'])
                md5_hash = hashlib.md5(data).hexdigest()
                
                # Determine filename
                filename = res.get('filename')
                if not filename:
                    ext = mimetypes.guess_extension(res.get('mime', '')) or '.bin' # Changed default to .bin
                    filename = f"{md5_hash}{ext}"
                
                filename = self._sanitize_filename(filename) # Sanitize filename
                
                # Check config for embed
                embed_images = self.config.get('content', {}).get('embed_images', False)
                mime = res.get('mime', '')
                is_image = mime.startswith('image/')
                
                should_save = True
                if embed_images and is_image:
                    should_save = False # Skip saving image file if embedding is enabled
                
                # Check for collision or just overwrite
                file_path = target_dir / filename
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                # Save recognition data if available
                # If NOT available and OCR is enabled, try OCR
                
                recognition = res.get('recognition')
                ocr_performed = False
                
                ocr_enabled = self.config.get('ocr', {}).get('enabled', False)
                if not recognition and ocr_enabled and is_image:
                     try:
                         import pytesseract
                         from PIL import Image
                         import io
                         
                         lang = self.config.get('ocr', {}).get('language', 'jpn')
                         image = Image.open(io.BytesIO(data))
                         
                         # Perform OCR
                         text = pytesseract.image_to_string(image, lang=lang)
                         if text.strip():
                             # Wrap in fake XML structure to match existing logic
                             # Or better, just store clean text and handle in formatter?
                             # For compatibility with formatter_html which expects XML parsing:
                             # <recoIndex><item><t>TEXT</t></item></recoIndex>
                             # We escape special chars for basic safety
                             import xml.sax.saxutils
                             safe_text = xml.sax.saxutils.escape(text)
                             recognition = f"<recoIndex><item><t>{safe_text}</t></item></recoIndex>"
                             ocr_performed = True
                             logging.info(f"   - OCR Performed on '{filename}'")
                     except Exception as e:
                         logging.warning(f"   - OCR Failed for '{filename}': {e}")

                if recognition:
                    reco_path = file_path.with_suffix(file_path.suffix + ".xml")
                    with open(reco_path, 'w', encoding='utf-8') as f:
                        f.write(recognition)
                    if ocr_performed:
                        logging.info(f"   - Resource '{filename}': OCR text saved.")
                    else:
                        logging.info(f"   - Resource '{filename}': Recognition data saved.")
                else:
                    logging.info(f"   - Resource '{filename}': No recognition data.")
                
                # Store full info in map
                res_info = {
                    'filename': filename,
                    'data_b64': res['data_b64'], 
                    'mime': mime,
                    'recognition': recognition 
                }
                res_map[md5_hash] = res_info
                
            except Exception as e:
                logging.error(f"Error processing resource: {e}") 
        
        # Populate instance var for easy access in create_intermediate_html
        self._resources_by_hash = res_map
        return res_map

    def _create_intermediate_html(self, enml_content, resource_map):
        """Parses ENML and transforms <en-media> and others."""
        soup = BeautifulSoup(enml_content, 'xml') # ENML is XML
        
        # Handle en-media
        for media in soup.find_all('en-media'):
            media_hash = media.get('hash')
            if media_hash in resource_map:
                # Prepend folder name for link
                filename = resource_map[media_hash]['filename']
                link_path = f"note_contents/{filename}"
                
                mime = media.get('type', '')
                
                if mime.startswith('image/'):
                     new_tag = soup.new_tag('img', src=link_path, alt=filename)
                     # We leave embedding to HtmlFormatter
                     # We leave OCR injection to HtmlFormatter (or handle it here? No, let's keep intermediate clean for MD)

                elif mime == 'application/pdf':
                    # Embed PDF for preview
                    # Use object tag for better compatibility and fallback
                    new_tag = soup.new_tag('object', data=link_path, type="application/pdf")
                    new_tag['width'] = "100%"
                    new_tag['height'] = "600px" # Default height
                    
                    # Fallback content
                    p = soup.new_tag('p')
                    p.string = f"PDF cannot be displayed. "
                    a = soup.new_tag('a', href=link_path)
                    a.string = f"Download {filename}"
                    p.append(a)
                    new_tag.append(p)
                else:
                    new_tag = soup.new_tag('a', href=link_path)
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
