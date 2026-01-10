import os
import base64
import hashlib
import mimetypes
import logging
from pathlib import Path
from bs4 import BeautifulSoup
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

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
        # Parallelization settings
        self.ocr_workers = config.get('ocr', {}).get('workers', 4)

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

        # Process Resources (with parallel OCR)
        seen_filenames = {}
        resource_map = self._process_resources_parallel(note_data.get('resources', []), contents_dir, seen_filenames)
        
        # CRITICAL: Update note_data with processed resources (includes OCR data)
        # This ensures formatters receive the processed resources with recognition/OCR text
        note_data['resources'] = resource_map
        
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
        """Sanitize string to be safe for filenames and limit length."""
        sanitized = re.sub(r'[<>:"/\\|?*]', self.sanitize_char, name).strip()
        # Limit length to avoid "File name too long" (255 is mostly limit, but keep safe margin)
        # Using 100 chars to leave room for timestamp prefixes and extensions
        if len(sanitized) > 100:
            sanitized = sanitized[:100].strip()
        return sanitized

    def _process_resources_parallel(self, resources, target_dir, seen_filenames):
        """Process resources with parallel OCR."""
        res_map = {}
        
        # First pass: Save files and prepare for OCR (sequential for filename collision handling)
        ocr_tasks = []
        for res in resources:
            if not res.get('data_b64'):
                continue
            
            try:
                data = base64.b64decode(res['data_b64'])
                md5_hash = hashlib.md5(data).hexdigest()
                
                # Determine filename
                filename = res.get('filename')
                if not filename:
                    ext = mimetypes.guess_extension(res.get('mime', '')) or '.bin'
                    filename = f"{md5_hash}{ext}"
                
                filename = self._sanitize_filename(filename)
                
                # Handle filename collision
                original_filename = filename
                counter = 1
                name_part, ext_part = os.path.splitext(filename)
                while filename in seen_filenames:
                    filename = f"{name_part}_{counter}{ext_part}"
                    counter += 1
                seen_filenames[filename] = True
                
                if filename != original_filename:
                    logging.debug(f"   - Renamed '{original_filename}' to '{filename}' to avoid collision")
                
                mime = res.get('mime', '')
                is_image = mime.startswith('image/')
                
                # Save file
                file_path = target_dir / filename
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                # Prepare for potential OCR
                recognition = res.get('recognition')
                ocr_enabled = self.config.get('ocr', {}).get('enabled', False)
                
                # Store base info
                res_info = {
                    'filename': filename,
                    'data_b64': res['data_b64'],
                    'mime': mime,
                    'recognition': recognition,
                    'ocr_position_data': None,
                    'file_path': file_path
                }
                res_map[md5_hash] = res_info
                
                # Queue for OCR if needed
                if not recognition and ocr_enabled and is_image:
                    ocr_tasks.append((md5_hash, data, filename, file_path))
                elif recognition:
                    # Save existing recognition data
                    reco_path = file_path.with_suffix(file_path.suffix + ".xml")
                    with open(reco_path, 'w', encoding='utf-8') as f:
                        f.write(recognition)
                    logging.info(f"   - Resource '{filename}': Recognition data saved.")
                else:
                    logging.info(f"   - Resource '{filename}': No recognition data.")
                    
            except Exception as e:
                logging.error(f"Error processing resource: {e}")
        
        # Second pass: Parallel OCR processing
        if ocr_tasks:
            # Filter out SVGs just in case logic above missed it or mime was wrong
            valid_tasks = []
            for task in ocr_tasks:
                md5_hash, data, filename, file_path = task
                if filename.lower().endswith('.svg'):
                    logging.warning(f"   - Skipping OCR for SVG: {filename}")
                    continue
                valid_tasks.append(task)
            
            ocr_tasks = valid_tasks
            
        if ocr_tasks:
            logging.info(f"   - Running OCR on {len(ocr_tasks)} images with {self.ocr_workers} workers...")
            with ThreadPoolExecutor(max_workers=self.ocr_workers) as executor:
                futures = {
                    executor.submit(self._perform_ocr, data, filename, file_path): (md5_hash, filename)
                    for md5_hash, data, filename, file_path in ocr_tasks
                }
                
                for future in as_completed(futures):
                    md5_hash, filename = futures[future]
                    try:
                        recognition, ocr_position_data = future.result()
                        res_map[md5_hash]['recognition'] = recognition
                        res_map[md5_hash]['ocr_position_data'] = ocr_position_data
                    except Exception as e:
                        logging.warning(f"   - OCR Failed for '{filename}': {e}")
        
        return res_map
    
    def _perform_ocr(self, data, filename, file_path):
        """Perform OCR on a single image. Returns (recognition_xml, position_data)."""
        import pytesseract
        from PIL import Image
        import io
        import json
        import xml.sax.saxutils
        import threading
        
        # Try to enable HEIC support
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
        except ImportError:
            pass

        lang = self.config.get('ocr', {}).get('language', 'jpn')
        
        try:
            # Open image and preprocess for better OCR accuracy
            image = Image.open(io.BytesIO(data))
            
            # Skip OCR for very small images (icons, spacers, tracking pixels)
            if image.width < 50 or image.height < 50:
                 logging.debug(f"   - Skipping OCR for small image {filename} ({image.width}x{image.height})")
                 return None, None
            
            # Robust conversion to RGB with white background handling for transparency
            # This handles 'P' (Palette), 'RGBA', 'LA' modes which might crash Tesseract or produce black backgrounds
            if image.mode in ('P', 'RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
                if image.mode == 'P':
                    image = image.convert('RGBA')
                
                # Create white background
                bg = Image.new('RGB', image.size, (255, 255, 255))
                # Paste image on top (using alpha channel if available)
                if image.mode == 'RGBA':
                    try:
                        bg.paste(image, mask=image.split()[3]) # 3 is alpha
                    except Exception:
                        bg.paste(image) # Fallback
                else:
                    bg.paste(image)
                image = bg
            elif image.mode != 'RGB':
                image = image.convert('RGB')

            # Downscale very large images to speed up OCR (max dimension 1500px)
            max_dim = 1500
            if max(image.width, image.height) > max_dim:
                scale = max_dim / float(max(image.width, image.height))
                new_size = (int(image.width * scale), int(image.height * scale))
                image = image.resize(new_size, resample=Image.LANCZOS)
                logging.info(f"   - Downscaled image {filename} to {new_size} for OCR speed")
            # 1. Convert to grayscale
            image = image.convert('L')
            # 2. Enhance contrast
            from PIL import ImageOps
            image = ImageOps.autocontrast(image)
            # 3. Binarize (simple threshold)
            image = image.point(lambda x: 0 if x < 128 else 255, '1')
            # 4. Upscale to improve recognition (optional, double size)
            width, height = image.size
            image = image.resize((width * 2, height * 2), resample=Image.LANCZOS)
            # 5. Convert back to RGB for Tesseract compatibility
            image = image.convert('RGB')
        except Exception as e:
            logging.warning(f"Failed to open image {filename} for OCR: {e}")
            return None, None
        
        # Perform OCR with position data
        try:
            # Perform OCR with tuned configuration for higher accuracy
            tesseract_config = '--oem 3 --psm 6 -c preserve_interword_spaces=1'
            ocr_data = pytesseract.image_to_data(image, lang=lang, config=tesseract_config, output_type=pytesseract.Output.DICT)
        except Exception as e:
            logging.warning(f"Tesseract failed for {filename}: {e}")
            return None, None
        
        # Build position-aware text data
        words_with_positions = []
        num_items = len(ocr_data['text'])
        
        # Helper to get value safely
        def get_safe(key, idx, default=0):
            lst = ocr_data.get(key, [])
            if idx < len(lst):
                return lst[idx]
            return default

        for i in range(num_items):
            text = ocr_data['text'][i].strip()
            # conf can be '-1' or similar
            try:
                conf = get_safe('conf', i, -1)
                
                if text and int(float(conf)) > 0:
                    words_with_positions.append({
                        'text': text,
                        'left': get_safe('left', i),
                        'top': get_safe('top', i),
                        'width': get_safe('width', i),
                        'height': get_safe('height', i),
                        'line_num': get_safe('line_num', i),
                        'block_num': get_safe('block_num', i),
                        'par_num': get_safe('par_num', i),
                        'conf': conf
                    })
            except (ValueError, TypeError, IndexError):
                continue
        
        recognition = None
        ocr_position_data = None
        
        if words_with_positions:
            ocr_position_data = {
                'image_width': image.width,
                'image_height': image.height,
                'words': words_with_positions
            }
            
            # Generate plain text with Japanese spacing fix
            plain_text = ' '.join([w['text'] for w in words_with_positions])
            # Remove spaces between Japanese characters
            plain_text = re.sub(r'([\u3000-\u30ff\u4e00-\u9fff])\s+([\u3000-\u30ff\u4e00-\u9fff])', r'\1\2', plain_text)
            
            safe_text = xml.sax.saxutils.escape(plain_text)
            recognition = f"<recoIndex><item><t>{safe_text}</t></item></recoIndex>"
            
            # Save files
            reco_path = file_path.with_suffix(file_path.suffix + ".xml")
            with open(reco_path, 'w', encoding='utf-8') as f:
                f.write(recognition)
            
            pos_path = file_path.with_suffix(file_path.suffix + ".ocr.json")
            with open(pos_path, 'w', encoding='utf-8') as f:
                json.dump(ocr_position_data, f, ensure_ascii=False)
            
            worker_id = threading.current_thread().name.split('_')[-1]
            logging.info(f"   - [Ocr-W{worker_id}] OCR: '{filename}' ({len(words_with_positions)} words)")
        
        return recognition, ocr_position_data

    def _process_resources(self, resources, target_dir, seen_filenames):
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
                
                # Handle filename collision
                original_filename = filename
                counter = 1
                name_part, ext_part = os.path.splitext(filename)
                while filename in seen_filenames:
                    filename = f"{name_part}_{counter}{ext_part}"
                    counter += 1
                seen_filenames[filename] = True
                
                if filename != original_filename:
                    logging.debug(f"   - Renamed '{original_filename}' to '{filename}' to avoid collision")
                
                # Check config for embed
                embed_images = self.config.get('content', {}).get('embed_images', False)
                mime = res.get('mime', '')
                # Specifically exclude SVG from being treated as standard image for OCR/Embed logic if needed
                # But HTML <img> works for SVG. We mostly care about OCR skipping.
                is_image = mime.startswith('image/')
                is_svg = 'svg' in mime or (res.get('filename') and res.get('filename').lower().endswith('.svg'))
                
                should_save = True
                if embed_images and is_image:
                    should_save = False # Skip saving image file if embedding is enabled
                
                # Save file
                file_path = target_dir / filename
                with open(file_path, 'wb') as f:
                    f.write(data)
                
                # Save recognition data if available
                # If NOT available and OCR is enabled, try OCR
                
                recognition = res.get('recognition')
                ocr_performed = False
                ocr_position_data = None  # New: Store position data for OCR
                image_dimensions = None   # New: Store image size for positioning
                
                ocr_enabled = self.config.get('ocr', {}).get('enabled', False)
                # Skip OCR for SVG
                if not recognition and ocr_enabled and is_image and not is_svg:
                     try:
                         import pytesseract
                         from PIL import Image
                         import io
                         import json
                         
                         lang = self.config.get('ocr', {}).get('language', 'jpn')
                         image = Image.open(io.BytesIO(data))
                         image_dimensions = {'width': image.width, 'height': image.height}
                         
                         # Perform OCR with position data
                         # image_to_data returns dict with: text, left, top, width, height, conf
                         ocr_data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
                         
                         # Build position-aware text data
                         words_with_positions = []
                         for i in range(len(ocr_data['text'])):
                             text = ocr_data['text'][i].strip()
                             # Safety check for lists
                             try:
                                 conf = ocr_data['conf'][i]
                                 if text and int(float(conf)) > 0:  # Filter empty and low-confidence
                                     words_with_positions.append({
                                         'text': text,
                                         'left': ocr_data['left'][i],
                                         'top': ocr_data['top'][i],
                                         'width': ocr_data['width'][i],
                                         'height': ocr_data['height'][i],
                                         'conf': conf
                                     })
                             except (IndexError, ValueError):
                                 continue
                         
                         if words_with_positions:
                             # Store as JSON for position-aware rendering
                             ocr_position_data = {
                                 'image_width': image.width,
                                 'image_height': image.height,
                                 'words': words_with_positions
                             }
                             
                             # Also generate plain text for backwards compatibility
                             plain_text = ' '.join([w['text'] for w in words_with_positions])
                             import xml.sax.saxutils
                             safe_text = xml.sax.saxutils.escape(plain_text)
                             recognition = f"<recoIndex><item><t>{safe_text}</t></item></recoIndex>"
                             ocr_performed = True
                             logging.info(f"   - OCR Performed on '{filename}' ({len(words_with_positions)} words)")
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
                
                # Save position data JSON if available
                if ocr_position_data:
                    pos_path = file_path.with_suffix(file_path.suffix + ".ocr.json")
                    import json
                    with open(pos_path, 'w', encoding='utf-8') as f:
                        json.dump(ocr_position_data, f, ensure_ascii=False)
                
                # Store full info in map
                res_info = {
                    'filename': filename,
                    'data_b64': res['data_b64'], 
                    'mime': mime,
                    'recognition': recognition,
                    'ocr_position_data': ocr_position_data  # New: Include position data
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
