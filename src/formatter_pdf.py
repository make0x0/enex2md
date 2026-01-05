import logging
import base64
import hashlib
import re
import mimetypes
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

        # Insert Content
        content_div = soup.find('div', class_='note-content')
        if not content_div:
            content_div = soup.find(id='note-content')
        
        if content_div:
            content_div.clear()
            content_soup = BeautifulSoup(intermediate_html, 'html.parser')
            
            # ALWAYS Embed images for PDF generation
            # WeasyPrint needs access to images; Base64 is reliable.
            # Or we can let WeasyPrint resolve paths if base_url is set correctly.
            # But embedding is safer given our complex path structure "note_contents/..."
            self._embed_images(content_soup, note_data.get('resources', []))
            
            content_div.append(content_soup)

        # PDF Output Path
        output_path = target_dir / f"{self._sanitize_filename(title)}.pdf"
        
        # Generate PDF
        html_str = str(soup)
        
        # Fix base URL for WeasyPrint if we didn't embed everything? 
        # But we embedded images. 
        # Assets (CSS)? If template has external CSS, might fail.
        # Default template has inline CSS.
        
        HTML(string=html_str, base_url=str(target_dir)).write_pdf(output_path)
        
        return output_path

    def _sanitize_filename(self, name):
        """Sanitize string to be safe for filenames."""
        sanitize_char = self.config.get('output', {}).get('filename_sanitize_char', '_')
        return re.sub(r'[<>:"/\\|?*]', sanitize_char, name).strip()
