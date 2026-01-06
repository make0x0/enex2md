import logging
import base64
import hashlib
import re
import os
import mimetypes
import shutil
import tempfile
from pathlib import Path
from bs4 import BeautifulSoup
from src.formatter_html import HtmlFormatter

# Playwright sync API
from playwright.sync_api import sync_playwright

class PdfFormatter(HtmlFormatter):
    def __init__(self, config):
        super().__init__(config)
        self.config = config
        self.playwright = None
        self.browser = None
        self._browser_initialized = False

    def _ensure_browser(self):
        """Lazy initialization of the Playwright browser."""
        if not self._browser_initialized:
            try:
                logging.info("Initializing Playwright (Chromium)...")
                self.playwright = sync_playwright().start()
                # Run headless. Increase timeout if needed.
                self.browser = self.playwright.chromium.launch(headless=True)
                self._browser_initialized = True
            except Exception as e:
                logging.error(f"Failed to initialize Playwright: {e}")
                self._browser_initialized = False
                # Cleanup if partially initialized
                self.close_browser()

    def close_browser(self):
        """Close browser and stop Playwright."""
        if self.browser:
            try:
                self.browser.close()
            except: pass
            self.browser = None
        
        if self.playwright:
            try:
                self.playwright.stop()
            except: pass
            self.playwright = None
        
        self._browser_initialized = False

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.close_browser()

    def generate(self, target_dir, intermediate_html, title, note_data):
        """Generates a PDF file from the note content using Playwright."""
        self._ensure_browser()
        if not self.browser:
            logging.error("Browser not available. Skipping PDF generation.")
            return None

        # Prepare HTML soup (Same logic as before, reusing HtmlFormatter logic partially)
        soup = BeautifulSoup(self.template, 'html.parser')
        
        # Set Title
        if soup.title:
            soup.title.string = title
        
        # Insert Meta
        meta_div = soup.find('div', class_='note-meta')
        if meta_div:
            meta_div.clear()
            created_p = soup.new_tag('p')
            created_p.string = f"Created: {note_data.get('created', '')}"
            meta_div.append(created_p)
            
            updated_date = note_data.get('updated')
            if updated_date:
                updated_p = soup.new_tag('p')
                updated_p.string = f"Updated: {updated_date}"
                meta_div.append(updated_p)
            
            tags = note_data.get('tags', [])
            if tags:
                tags_p = soup.new_tag('p')
                tags_p.string = f"Tags: {', '.join(tags)}"
                meta_div.append(tags_p)
            
            source_url = note_data.get('source_url')
            if source_url:
                url_p = soup.new_tag('p')
                url_a = soup.new_tag('a', href=source_url, target="_blank")
                url_a.string = f"Source URL: {source_url}"
                url_p.append(url_a)
                meta_div.append(url_p)

            # Location (Optional)
            location = note_data.get('location', {})
            add_loc = self.config.get('content', {}).get('add_location_link', True)
            if add_loc and location.get('latitude') and location.get('longitude'):
                lat = location['latitude']
                lon = location['longitude']
                # Offline Reverse Geocoding
                loc_name = ""
                try:
                    import reverse_geocoder as rg
                    results = rg.search((lat, lon))
                    if results:
                        r = results[0]
                        loc_name = f"{r.get('name', '')}, {r.get('cc', '')}"
                except: pass
                
                loc_p = soup.new_tag('p')
                map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                loc_a = soup.new_tag('a', href=map_url, target="_blank")
                display_text = f"📍 Location: {loc_name} ({lat:.4f}, {lon:.4f})" if loc_name else f"📍 Location ({lat:.4f}, {lon:.4f})"
                loc_a.string = display_text
                loc_p.append(loc_a)
                meta_div.append(loc_p)

        # Update Heading
        h1 = soup.find('h1')
        if h1:
            h1.string = title

        # CSS - Chromium rendering is good, but we can add some print styles
        pdf_style = soup.new_tag('style')
        pdf_style.string = """
            @page { margin: 20mm; }
            body { 
                font-family: "Noto Sans CJK JP", "Meiryo", sans-serif;
                line-height: 1.6;
                color: #333;
                width: 100%;
                margin: 0;
            }
            img { max-width: 100%; height: auto; display: block; margin: 10px auto; }
            table { width: 100%; border-collapse: collapse; margin-bottom: 1em; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }
            th { background-color: #f5f5f5; }
            pre { background: #f8f8f8; padding: 10px; overflow-x: auto; white-space: pre-wrap; word-wrap: break-word; }
            a { color: #0066cc; text-decoration: none; }
            
            /* Print specific adjustments */
            @media print {
                a { text-decoration: underline; }
                .no-print { display: none; }
                h1, h2, h3 { page-break-after: avoid; }
                img, table, pre { page-break-inside: avoid; }
            }
        """
        if soup.head:
            soup.head.append(pdf_style)
        elif soup.body:
             soup.body.insert(0, pdf_style)

        # Smart PDF Mode Check
        # If the note contains ONLY one PDF attachment (and minimal text), copy original PDF.
        resources = note_data.get('resources', [])
        # Resources can be list or dict
        resources_list = list(resources.values()) if isinstance(resources, dict) else resources

        pdf_resources = [r for r in resources_list if isinstance(r, dict) and r.get('mime') == 'application/pdf']
        
        # Check text length
        soup_body_text = BeautifulSoup(intermediate_html, 'html.parser').get_text().strip()
        is_minimal_text = len(soup_body_text) < 100

        if len(pdf_resources) == 1 and is_minimal_text:
             pdf_res = pdf_resources[0]
             # Search for the PDF file in note_contents
             note_contents_dir = target_dir / "note_contents"
             if note_contents_dir.exists():
                 pdf_files = list(note_contents_dir.glob("*.pdf"))
                 # We try to match by filename if possible, or just grab the only one
                 target_filename = pdf_res.get('filename')
                 candidate = None
                 if target_filename and (note_contents_dir / target_filename).exists():
                     candidate = note_contents_dir / target_filename
                 elif len(pdf_files) == 1:
                     candidate = pdf_files[0]
                 
                 if candidate:
                     output_filename = f"{self._sanitize_filename(title)}.pdf"
                     output_path = target_dir / output_filename
                     shutil.copy2(candidate, output_path)
                     
                     # Timestamp
                     ts_date = note_data.get('updated') or note_data.get('created')
                     if ts_date:
                         try:
                             ts_timestamp = ts_date.timestamp()
                             os.utime(output_path, (ts_timestamp, ts_timestamp))
                         except: pass
                     
                     logging.info(f"Smart PDF Mode: Copied original PDF for '{title}'")
                     self._copy_to_pdf_folder(output_path, target_dir, note_data, exclude_filenames={candidate.name})
                     return output_path

        # Insert Content
        content_div = soup.find('div', class_='note-content')
        if not content_div:
             content_div = soup.find(id='note-content')

        if content_div:
             content_div.clear()
             content_soup = BeautifulSoup(intermediate_html, 'html.parser')
             
             self._embed_images_pdf(content_soup, resources_list)
             content_div.append(content_soup)

        # Generate PDF using Playwright
        output_filename = f"{self._sanitize_filename(title)}.pdf"
        output_path = target_dir / output_filename

        try:
            page = self.browser.new_page()
            
            # set_content with wait_until='networkidle' ensures images (embedded) are loaded
            # Since we embed images as base64, this should be fast and reliable.
            page.set_content(str(soup), wait_until="networkidle")
            
            # Print to PDF
            # A4, Print background graphics
            page.pdf(path=str(output_path), format="A4", print_background=True, margin={"top": "20mm", "bottom": "20mm", "left": "20mm", "right": "20mm"})
            
            page.close()
            
            # Timestamp setting
            ts_date = note_data.get('updated') or note_data.get('created')
            if ts_date:
                try:
                    import time
                    ts_timestamp = ts_date.timestamp()
                    os.utime(output_path, (ts_timestamp, ts_timestamp))
                except: pass

            # Copy to _PDF folder
            self._copy_to_pdf_folder(output_path, target_dir, note_data)

            return output_path

        except Exception as e:
            logging.error(f"Playwright PDF generation failed for '{title}': {e}")
            # Try to restart browser as it might be crashed
            self.close_browser()
            return None

    def _copy_to_pdf_folder(self, pdf_path, target_dir, note_data=None, exclude_filenames=None):
        """Copy the generated PDF to a _PDF folder, maintaining hierarchy."""
        try:
            note_folder = target_dir.name
            enex_folder = target_dir.parent.name
            output_root = target_dir.parent.parent
            
            # Create _PDF folder structure (output_root / _PDF / enex_folder)
            pdf_dest_dir = output_root / "_PDF" / enex_folder
            pdf_dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Prefix filename with date if available
            filename = pdf_path.name
            if note_data:
                created = note_data.get('created')
                date_part = ""
                if created:
                    date_part = str(created).split(' ')[0]
                
                if date_part and not filename.startswith(date_part):
                        filename = f"{date_part}_{filename}"

            # Copy the PDF
            dest_path = pdf_dest_dir / filename
            shutil.copy2(pdf_path, dest_path)
            logging.debug(f"Copied PDF to: {dest_path}")
            
            # --- Attachment Handling ---
            pdf_stem = Path(filename).stem
            attachment_folder_name = f"{pdf_stem}_note_contents"
            source_attachments_dir = target_dir / "note_contents"
            
            if source_attachments_dir.exists():
                dest_attachments_dir = pdf_dest_dir / attachment_folder_name
                
                excluded_extensions = {
                    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff',
                    '.xml', '.json'
                }
                
                valid_attachments = []
                for f in source_attachments_dir.iterdir():
                    if f.is_file() and not f.name.startswith('.'):
                        if f.suffix.lower() not in excluded_extensions:
                            if exclude_filenames and f.name in exclude_filenames:
                                continue
                            valid_attachments.append(f)
                
                if valid_attachments:
                    if dest_attachments_dir.exists():
                        shutil.rmtree(dest_attachments_dir)
                    dest_attachments_dir.mkdir(parents=True, exist_ok=True)
                    
                    for f in valid_attachments:
                        shutil.copy2(f, dest_attachments_dir / f.name)
                        
                    logging.info(f"Copied {len(valid_attachments)} attachments to: {dest_attachments_dir}")

        except Exception as e:
            logging.warning(f"Failed to copy PDF to _PDF folder: {e}")

    def _embed_images_pdf(self, soup, resource_list):
        """Embed images as Base64 and inject OCR text with PDF-friendly visibility."""
        if not resource_list:
            return

        res_map_by_filename = {r.get('filename'): r for r in resource_list if isinstance(r, dict)}
        
        for img in list(soup.find_all('img')):
            src = img.get('src')
            if not src: continue
            filename = Path(src).name
            res = res_map_by_filename.get(filename)
            if res:
                # Embed Base64
                if res.get('data_b64') and res.get('mime'):
                    img['src'] = f"data:{res['mime']};base64,{res['data_b64']}"
                
                # Inject OCR Text
                ocr_position_data = res.get('ocr_position_data')
                
                if ocr_position_data and ocr_position_data.get('words'):
                    img_width = ocr_position_data['image_width']
                    img_height = ocr_position_data['image_height']
                    words = ocr_position_data['words']
                    
                    wrapper = soup.new_tag('div', style="position:relative; display:inline-block;")
                    img.wrap(wrapper)
                    
                    text_layer = soup.new_tag('div', style=f"""
                        position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                        z-index: 10; pointer-events: none;
                    """)
                    
                    for word_info in words:
                        left_pct = (word_info['left'] / img_width) * 100
                        top_pct = (word_info['top'] / img_height) * 100
                        width_pct = (word_info['width'] / img_width) * 100
                        height_pct = (word_info['height'] / img_height) * 100
                        
                        # Font size constraint
                        font_size_pt = max(4, min(word_info['height'] * 0.6, 48))
                        
                        word_span = soup.new_tag('span', style=f"""
                            position: absolute;
                            left: {left_pct:.2f}%; top: {top_pct:.2f}%;
                            width: {width_pct:.2f}%; height: {height_pct:.2f}%;
                            color: rgba(0,0,0,0);
                            font-size: {font_size_pt:.1f}pt;
                            line-height: 1;
                            white-space: nowrap; overflow: hidden;
                        """)
                        word_span.string = word_info['text']
                        text_layer.append(word_span)
                    
                    wrapper.append(text_layer)
                    
                elif res.get('recognition'):
                    # Fallback non-positioned OCR
                    recognition_xml = res.get('recognition')
                    text_content = self._extract_text_from_reco(recognition_xml)
                    if text_content:
                        wrapper = soup.new_tag('div', style="position:relative; display:inline-block;")
                        img.wrap(wrapper)
                        new_div = soup.new_tag('div', style="""
                            position: absolute; top: 0; left: 0; width: 100%; height: 100%;
                            color: rgba(0,0,0,0); font-size: 12pt; overflow: hidden; z-index: 10;
                        """)
                        new_div.string = text_content
                        wrapper.append(new_div)

    def _extract_text_from_reco(self, reco_xml):
        """Extracts plain text from recognition XML."""
        if not reco_xml: return ""
        try:
            soup = BeautifulSoup(reco_xml, 'xml')
            return soup.get_text(separator=' ').strip()
        except:
            return ""

    def _sanitize_filename(self, name):
         sanitize_char = self.config.get('output', {}).get('filename_sanitize_char', '_')
         return re.sub(r'[<>:"/\\|?*]', sanitize_char, name).strip()
