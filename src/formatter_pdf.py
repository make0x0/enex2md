import logging
import base64
import hashlib
import re
import mimetypes
import shutil
from pathlib import Path
from bs4 import BeautifulSoup
from src.formatter_html import HtmlFormatter

class PdfFormatter(HtmlFormatter):
    def __init__(self, config):
        super().__init__(config)
        self.config = config

    def generate(self, target_dir, intermediate_html, title, note_data):
        """Generates a PDF file from the note content."""
        try:
            from weasyprint import HTML, CSS
        except ImportError:
            logging.error("WeasyPrint not found. Please install PDF support dependencies.")
            return None

        # Reuse HtmlFormatter logic to prepare the full HTML structure
        # We need the HTML string, but HtmlFormatter.generate writes to file.
        # Let's duplicate the relevant construction logic here or refactor HtmlFormatter later.
        # For now, to avoid breaking HtmlFormatter, I'll copy the construction logic logic (mostly).
        
        # Parse template
        soup = BeautifulSoup(self.template, 'html.parser')
        
        # Set Title
        if soup.title:
            soup.title.string = title
        
        # Insert Meta (Simplified for PDF)
        meta_div = soup.find('div', class_='note-meta')
        if meta_div:
            meta_div.clear()
            created_p = soup.new_tag('p')
            created_p.string = f"Created: {note_data.get('created', '')}"
            meta_div.append(created_p)
            
            tags = note_data.get('tags', [])
            if tags:
                tags_p = soup.new_tag('p')
                tags_p.string = f"Tags: {', '.join(tags)}"
                meta_div.append(tags_p)
            
            # Source URL often useful in PDF too
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
        
        # Remove scripts for PDF (WeasyPrint doesn't run JS)
        if soup.body:
             for s in soup.body.find_all('script'):
                 s.decompose()

        # Add PDF-specific CSS for image sizing
        # Ensures tall images (like receipts) fit within page bounds
        pdf_style = soup.new_tag('style')
        pdf_style.string = """
            img {
                max-width: 100%;
                max-height: 250mm;  /* A4 page is 297mm, leave margin */
                width: auto;
                height: auto;
                object-fit: contain;
                page-break-inside: avoid;
            }
            .note-content {
                page-break-inside: auto;
            }
        """
        if soup.head:
            soup.head.append(pdf_style)
        elif soup.body:
            soup.body.insert(0, pdf_style)

        # Insert Content
        content_div = soup.find('div', class_='note-content')
        if not content_div:
            content_div = soup.find(id='note-content')
        
        if content_div:
            content_div.clear()
            content_soup = BeautifulSoup(intermediate_html, 'html.parser')
            
            # Smart PDF Mode Check
            # If the note contains ONLY one PDF attachment (and minimal text), copy original PDF.
            resources = note_data.get('resources', [])
            
            # resources might be a dict keyed by MD5 hash (from converter.py)
            # Convert to list for consistent iteration
            if isinstance(resources, dict):
                resources_list = list(resources.values())
            else:
                resources_list = resources
            
            pdf_resources = [r for r in resources_list if isinstance(r, dict) and r.get('mime') == 'application/pdf']
            
            # Check text length (strip whitespace)
            text_content = content_soup.get_text().strip()
            # Allow some title overlap or small noise (e.g. filename repetition)
            # 100 chars is arbitrary but safe for "just a file" notes
            is_minimal_text = len(text_content) < 100 
            
            if len(pdf_resources) == 1 and is_minimal_text:
                pdf_res = pdf_resources[0]
                # We need to find the file.
                # In converter.py, we decided filename. We need to find the correct file in target_dir/note_contents
                # We can iterate the dir or try to match.
                # Or reuse logic from HtmlFormatter._embed_images if we had it.
                # Simple approach: Search for file in note_contents with matching MD5?
                # Or just grab the first PDF file in note_contents if there is only 1 PDF resource?
                
                # Let's search by extension
                note_contents_dir = target_dir / "note_contents"
                if note_contents_dir.exists():
                     pdf_files = list(note_contents_dir.glob("*.pdf"))
                     if len(pdf_files) == 1:
                         # Found candidate
                         original_pdf = pdf_files[0]
                         output_path = target_dir / f"{self._sanitize_filename(title)}.pdf"
                         shutil.copy2(original_pdf, output_path)
                         logging.info(f"Smart PDF Mode: Copied original PDF for '{title}'")
                         return output_path
                
            # Match logic from HtmlFormatter but apply PDF-specific visibility
            # In HTML we used display:none. For PDF we want opacity:0 and position:absolute
            # We need to ensure existing ocr-text divs are styled correctly.
            # Let's add a style tag.
            style_tag = soup.new_tag('style')
            # Use specific class if possible, or generic display:none override?
            # HtmlFormatter uses <div style="display:none;">. 
            # We need to change that INLINE style or override it.
            # Since inline style has high specificity, we must replace the inline attribute or use !important on ID/Class.
            # But HtmlFormatter injected via `_embed_images`.
            
            # Let's override `_embed_images` behavior or post-process the soup.
            # The base definition of `_embed_images` in `HtmlFormatter` uses:
            # new_div = soup.new_tag('div', style="display:none;")
            
            # So we iterate and change style.
            # NOTE: We skip calling _embed_images here because _embed_images_pdf handles embedding AND OCR injection
            # self._embed_images(content_soup, resources_list)
            
            # Post-process to fix visibility for PDF
            for div in content_soup.find_all('div', style="display:none;"):
                # Check if it looks like our OCR div (has text content)
                # Better: Check if it follows an image?
                # Or just checking style="display:none;" is risky?
                # To be safe, let's redefine `_embed_images` in PdfFormatter to use a class.
                pass
            
            # Call our custom PDF-specific embedding and OCR injection
            self._embed_images_pdf(content_soup, resources_list)
            
            content_div.append(content_soup)

        # PDF Output Path
        output_path = target_dir / f"{self._sanitize_filename(title)}.pdf"
        
        # Generate PDF
        html_str = str(soup)
        
        # Fix base URL for WeasyPrint if we didn't embed everything? 
        # But we embedded images. 
        
        HTML(string=html_str, base_url=str(target_dir)).write_pdf(output_path)
        
        return output_path

    def _embed_images_pdf(self, soup, resources):
        """Embed images as Base64 and inject OCR text with PDF-friendly visibility."""
        if not resources:
            return

        # resources might be a dict keyed by MD5 hash (from converter.py)
        # or a list of resource dicts. Handle both cases.
        if isinstance(resources, dict):
            resource_list = list(resources.values())
        else:
            resource_list = resources
        
        # Map by filename for lookup
        res_map_by_filename = {r.get('filename'): r for r in resource_list if isinstance(r, dict)}
        
        # Find all img tags
        # We might modify the tree, so iterate over a list
        for img in list(soup.find_all('img')):
            src = img.get('src')
            if not src:
                continue
            
            # src is likely "note_contents/filename.png"
            filename = Path(src).name
            
            res = res_map_by_filename.get(filename)
            if res:
                # Embed Base64
                if res.get('data_b64') and res.get('mime'):
                    img['src'] = f"data:{res['mime']};base64,{res['data_b64']}"
                
                # Inject OCR Text with position awareness
                ocr_position_data = res.get('ocr_position_data')
                
                if ocr_position_data and ocr_position_data.get('words'):
                    # Position-aware OCR: Place each word at its exact location
                    img_width = ocr_position_data['image_width']
                    img_height = ocr_position_data['image_height']
                    words = ocr_position_data['words']
                    
                    # Wrap image in a relative container
                    wrapper = soup.new_tag('div', style="position:relative; display:inline-block;")
                    img.wrap(wrapper)
                    
                    # Create a text overlay container sized to match image
                    text_layer = soup.new_tag('div', style=f"""
                        position: absolute;
                        top: 0;
                        left: 0;
                        width: 100%;
                        height: 100%;
                        z-index: 10;
                        pointer-events: none;
                    """)
                    
                    # Add each word as a positioned span
                    for word_info in words:
                        # Calculate position as percentage of image size
                        left_pct = (word_info['left'] / img_width) * 100
                        top_pct = (word_info['top'] / img_height) * 100
                        width_pct = (word_info['width'] / img_width) * 100
                        height_pct = (word_info['height'] / img_height) * 100
                        
                        # Estimate font size in pt based on word height
                        # Assume image roughly fits on A4 page (~800px typical image height = ~500pt page height)
                        # So we scale: word_height_px * (500pt / img_height_px) * 0.8 (factor for line-height)
                        font_size_pt = max(4, min(word_info['height'] * 0.6, 48))  # Clamp between 4pt and 48pt
                        
                        word_span = soup.new_tag('span', style=f"""
                            position: absolute;
                            left: {left_pct:.2f}%;
                            top: {top_pct:.2f}%;
                            width: {width_pct:.2f}%;
                            height: {height_pct:.2f}%;
                            color: rgba(0,0,0,0);
                            font-size: {font_size_pt:.1f}pt;
                            line-height: 1;
                            white-space: nowrap;
                            overflow: hidden;
                        """)
                        word_span.string = word_info['text']
                        text_layer.append(word_span)
                    
                    wrapper.append(text_layer)
                    logging.debug(f"Positioned {len(words)} OCR words for '{filename}'")
                    
                elif res.get('recognition'):
                    # Fallback: Use old method for non-positioned OCR (e.g., Evernote native)
                    recognition_xml = res.get('recognition')
                    text_content = self._extract_text_from_reco(recognition_xml)
                    if text_content:
                        wrapper = soup.new_tag('div', style="position:relative; display:inline-block;")
                        img.wrap(wrapper)
                        
                        new_div = soup.new_tag('div', style="""
                            position: absolute; 
                            top: 0; 
                            left: 0; 
                            width: 100%; 
                            height: 100%;
                            color: rgba(0,0,0,0); 
                            font-size: 12pt;
                            overflow: hidden;
                            z-index: 10;
                            line-height: 1.2;
                        """)
                        new_div.string = text_content
                        wrapper.append(new_div)

    def _sanitize_filename(self, name):
        """Sanitize string to be safe for filenames."""
        sanitize_char = self.config.get('output', {}).get('filename_sanitize_char', '_')
        return re.sub(r'[<>:"/\\|?*]', sanitize_char, name).strip()
