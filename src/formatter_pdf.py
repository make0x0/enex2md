import logging
import base64
import hashlib
import re
import os
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
                url_a = soup.new_tag('a', href=source_url)
                url_a.string = f"Source URL: {source_url}"
                url_p.append(url_a)
                meta_div.append(url_p)
                
            location = note_data.get('location', {})
            add_loc = self.config.get('content', {}).get('add_location_link', True)
            if add_loc and location.get('latitude') and location.get('longitude'):
                lat = location['latitude']
                lon = location['longitude']
                
                # Reverse Geoding (Offline)
                loc_name = ""
                try:
                    import reverse_geocoder as rg
                    # rg.search returns a list of dicts, we take the first one
                    results = rg.search((lat, lon))
                    if results:
                        r = results[0]
                        loc_name = f"{r.get('name', '')}, {r.get('cc', '')}"
                except ImportError:
                    pass
                except Exception as e:
                    logging.warning(f"Reverse geocoding failed: {e}")
                
                loc_p = soup.new_tag('p')
                map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                loc_a = soup.new_tag('a', href=map_url)
                display_text = f"📍 Location: {loc_name} ({lat:.4f}, {lon:.4f})" if loc_name else f"📍 Location ({lat:.4f}, {lon:.4f})"
                loc_a.string = display_text
                loc_p.append(loc_a)
                meta_div.append(loc_p)

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
        # WeasyPrint doesn't fully support object-fit, so use simpler constraints
        pdf_style = soup.new_tag('style')
        pdf_style.string = """
            @page {
                size: A4;
                margin: 10mm;
            }
            h1 {
                page-break-after: avoid;
                margin-bottom: 5mm;
            }
            img {
                max-width: 100%;
                max-height: 270mm;  /* A4 is 297mm, minus margins */
                display: block;
                display: block;
                margin: 0 auto;
            }
            a {
                color: blue;
                text-decoration: underline;
            }
            .note-content {
                page-break-before: avoid;
            }
            .note-content img {
                page-break-inside: avoid;
                page-break-before: auto;
            }
        """
        if soup.head:
            soup.head.append(pdf_style)
        elif soup.body:
            soup.body.insert(0, pdf_style)

        # Fit Width Mode (Aggressive CSS)
        if self.config.get('pdf', {}).get('fit_mode', False):
            logging.info(f"PDF Fit Width Mode: Enabled for '{title}'")
            fit_style = soup.new_tag('style')
            fit_style.string = """
                /* Safer Fit Width Mode */
                
                /* Constrain Max Width but DON'T Force Width */
                img, figure, video, canvas {
                    max-width: 100% !important;
                    height: auto !important;
                    box-sizing: border-box !important;
                }
                
                /* Wrap text to prevent overflow, but be careful with pre */
                body {
                    overflow-wrap: break-word !important; 
                    word-wrap: break-word !important;
                }
                
                /* Pre/Code: Force wrap to prevent horizontal scroll need */
                pre, code {
                    white-space: pre-wrap !important; 
                    max-width: 100% !important;
                }
                
                /* Table: Allow shrink if possible, but don't break layout */
                table {
                    max-width: 100% !important;
                    /* table-layout: fixed; <--- REMOVED: Destroys layout tables */
                    /* width: 100%; <--- REMOVED: Forces expansion to page width */
                }
            """
            if soup.head:
                soup.head.append(fit_style)
            elif soup.body:
                soup.body.insert(0, fit_style)

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
                         
                         # Smart Mode: Update timestamp to match note data
                         ts_date = note_data.get('updated') or note_data.get('created')
                         if ts_date:
                             try:
                                 ts_timestamp = ts_date.timestamp()
                                 os.utime(output_path, (ts_timestamp, ts_timestamp))
                                 logging.debug(f"Smart PDF Mode: Set timestamp to {ts_date}")
                             except Exception as e:
                                 logging.warning(f"Smart PDF Mode: Failed to set timestamp: {e}")

                         logging.info(f"Smart PDF Mode: Copied original PDF for '{title}'")
                         # Pass the original PDF filename to exclude it from attachments
                         self._copy_to_pdf_folder(output_path, target_dir, note_data, exclude_filenames={original_pdf.name})
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
        output_filename = f"{self._sanitize_filename(title)}.pdf"
        output_path = target_dir / output_filename
        
        # Attachment Link Rewriting for PDF
        # We want links in PDF to point to: ./[PDF_DATE_NAME]_note_contents/file.zip
        # Calc the prefix similarly to _copy_to_pdf_folder
        
        date_part = ""
        created = note_data.get('created')
        if created:
            date_part = str(created).split(' ')[0]
        
        final_pdf_filename = output_filename
        if date_part and not output_filename.startswith(date_part):
            final_pdf_filename = f"{date_part}_{output_filename}"
            
        pdf_stem = Path(final_pdf_filename).stem
        attachment_folder_name = f"{pdf_stem}_note_contents"
        
        # Iterate all <a> tags and rewrite if pointing to note_contents/
        for a in soup.find_all('a'):
            href = a.get('href', '')
            if href.startswith('note_contents/'):
                filename = href.split('/')[-1]
                # Rewrite to new relative path
                new_href = f"./{attachment_folder_name}/{filename}"
                a['href'] = new_href
                # Add a small icon or text to indicate attachment? (Optional)
                # a.string = f"📎 {a.string}" 

        # Add PDF Metadata
        # WeasyPrint maps <meta> tags in head to PDF Info
        # <meta name="author" content="..."> -> Author
        # <meta name="description" content="..."> -> Subject
        # <meta name="keywords" content="..."> -> Keywords
        # <meta name="generator" content="..."> -> Creator
        # <meta name="dcterms.created" content="..."> -> CreationDate
        # <meta name="dcterms.modified" content="..."> -> ModDate
        
        if not soup.head:
            soup.insert(0, soup.new_tag("head"))
            
        def add_meta(name, content):
            if content:
                meta = soup.new_tag("meta", attrs={"name": name, "content": str(content)})
                soup.head.append(meta)

        add_meta("author", note_data.get('author', ''))
        add_meta("dcterms.created", note_data.get('created', ''))
        if note_data.get('updated'):
            add_meta("dcterms.modified", note_data.get('updated'))
        add_meta("generator", "enex2md")

        # Generate PDF
        html_str = str(soup)
        
        # presentational_hints=True enables background colors and other HTML presentation styles
        HTML(string=html_str, base_url=str(target_dir)).write_pdf(
            output_path,
            presentational_hints=True
        )
        
        # Update Filesystem Timestamp (os.utime)
        # Use updated date if available, else created date
        ts_date = note_data.get('updated') or note_data.get('created')
        if ts_date:
            try:
                # Assuming ts_date is a datetime object (it should be from parser)
                import time
                ts_timestamp = ts_date.timestamp()
                os.utime(output_path, (ts_timestamp, ts_timestamp))
                logging.debug(f"Set PDF timestamp to {ts_date}")
            except Exception as e:
                logging.warning(f"Failed to set timestamp for PDF: {e}")

        # Copy PDF to _PDF folder (maintains directory structure)
        self._copy_to_pdf_folder(output_path, target_dir, note_data)
        
        return output_path
    
    def _copy_to_pdf_folder(self, pdf_path, target_dir, note_data=None, exclude_filenames=None):
        """Copy the generated PDF to a _PDF folder, maintaining hierarchy."""
        try:
            # Get the output root (parent of enex folder, which is parent of note folder)
            # Structure: output_root / enex_stem / note_folder / file.pdf
            # We want: output_root / _PDF / enex_stem / file.pdf (Flattened)
            
            note_folder = target_dir.name  # e.g., "2025-01-01_MyNote"
            enex_folder = target_dir.parent.name  # e.g., "MyNotebook"
            output_root = target_dir.parent.parent  # The base output directory
            
            # Create _PDF folder structure (output_root / _PDF / enex_folder)
            pdf_dest_dir = output_root / "_PDF" / enex_folder
            pdf_dest_dir.mkdir(parents=True, exist_ok=True)
            
            # Prefix filename with date if available
            filename = pdf_path.name
            if note_data:
                created = note_data.get('created')
                date_part = ""
                # created is usually "YYYY-MM-DD HH:MM:SS" or similar
                # We want "YYYY-MM-DD_" prefix
                if created:
                    date_part = str(created).split(' ')[0]
                
                if date_part and not filename.startswith(date_part):
                        filename = f"{date_part}_{filename}"

            # Copy the PDF
            dest_path = pdf_dest_dir / filename
            shutil.copy2(pdf_path, dest_path)
            logging.debug(f"Copied PDF to: {dest_path}")
            
            # --- Attachment Handling ---
            # If there were attachments (links to note_contents/), we need to copy them too.
            # The PDF generation logic (to be updated) rewrote links to point to "{filename_stem}_note_contents"
            
            pdf_stem = Path(filename).stem
            attachment_folder_name = f"{pdf_stem}_note_contents"
            
            # Source of attachments: target_dir/note_contents
            source_attachments_dir = target_dir / "note_contents"
            
            if source_attachments_dir.exists():
                # We need to check if any file in here was actually referenced/linked in the PDF.
                # Since we don't have the list of referenced files easily here, let's copy ALL files 
                # that are NOT images used in the PDF (images are embedded).
                # Actually, copying everything is safer for completeness.
                
                # Destination: _PDF/enex_folder/attachment_folder_name
                dest_attachments_dir = pdf_dest_dir / attachment_folder_name
                
                # Check if we should copy
                # Filter out images, XML, JSON, and hidden files
                excluded_extensions = {
                    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff',
                    '.xml', '.json'
                }
                
                valid_attachments = []
                valid_attachments = []
                for f in source_attachments_dir.iterdir():
                    if f.is_file() and not f.name.startswith('.'):
                        if f.suffix.lower() not in excluded_extensions:
                            # Also check explicit exclusion (e.g. main PDF)
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
