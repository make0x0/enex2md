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
                url_p.string = "Source URL: "
                url_a = soup.new_tag('a', href=source_url, target="_blank", rel="noopener noreferrer")
                url_a.string = source_url
                url_p.append(url_a)
                meta_div.append(url_p)
                
            location = note_data.get('location', {})
            add_loc = self.config.get('content', {}).get('add_location_link', True)
            if add_loc and location.get('latitude') and location.get('longitude'):
                lat = location['latitude']
                lon = location['longitude']
                
                # Reverse Geoding
                loc_name = ""
                try:
                    import reverse_geocoder as rg
                    # rg.search returns a list of dicts, we take the first one
                    results = rg.search((lat, lon))
                    if results:
                        # e.g., {'name': 'Tokyo', 'admin1': 'Tokyo', 'cc': 'JP'}
                        r = results[0]
                        loc_name = f"{r.get('name', '')}, {r.get('cc', '')}"
                except ImportError:
                    pass
                except Exception as e:
                    logging.warning(f"Reverse geocoding failed: {e}")
                
                loc_p = soup.new_tag('p')
                # Google Maps link
                map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                loc_a = soup.new_tag('a', href=map_url, target="_blank", rel="noopener noreferrer")
                display_text = f"📍 Location: {loc_name} ({lat:.4f}, {lon:.4f})" if loc_name else f"📍 Location ({lat:.4f}, {lon:.4f})"
                loc_a.string = display_text
                loc_p.append(loc_a)
                meta_div.append(loc_p)

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
            
            # Post-process for embedding if enabled
            embed_images = self.config.get('content', {}).get('embed_images', False)
            if embed_images:
                 self._embed_images(content_soup, note_data.get('resources', []))
            
            # content_div.append(content_soup) # This can cause IndexError in some BS4 versions
            # Safe append:
            for element in list(content_soup.contents):
                content_div.append(element)
        
        output_path = target_dir / "index.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(str(soup))
            
        return output_path

    def _embed_images(self, soup, resources):
        """Replaces img src with Base64 data and adds OCR text."""
        import base64
        import hashlib
        
        # Build lookup map from resources (md5 -> resource)
        # Note: We need to match filename in link_path to resource
        # link_path is like "note_contents/filename.ext"
        
        # But wait, how do we match?
        # converter.py generated filenames based on hash or original filename.
        # We can try to reconstruct the map or match by filename.
        # But filename uniqueness logic in converter was: sanitize(res['filename'] or hash+ext)
        # Re-implementing that logic here is risky.
        
        # Better approach: Iterate img tags, get filename from src, find matching resource.
        # Img src is "note_contents/FILENAME"
        
        # Handle resources as dict (keyed by MD5) or list
        if isinstance(resources, dict):
            resource_list = list(resources.values())
        else:
            resource_list = resources if resources else []
        
        # Let's map filename -> resource
        filename_map = {}
        for res in resource_list:
            if not isinstance(res, dict) or not res.get('data_b64'): continue
            
            # Reconstruct filename logic from converter...
            # This is BAD duplication.
            # OPTION: pass 'resource_map' from converter to here via note_data?
            # note_data currently structure from PARSER.
            # converter.convert_note RETURNS 'target_dir, intermediate_html, title, created, full_data'
            # 'full_data' IS note_data.
            pass

        # Since we don't have the resource_map here, and re-calculating filenames is error prone,
        # let's try to match by MD5 if possible?
        # But HTML has filenames.
        
        # OK, let's look at available data.
        # If we can't reliably map, we might fail to embed some.
        
        # Alternative: We can compute MD5 of all resources again and match keys?
        # But we don't know which MD5 corresponds to which filename easily without logic.
        
        # Let's import logic or duplicates?
        # Or, just iterate resources, calculate "candidate" filename using same logic and store in map.
        
        import mimetypes
        import re
        sanitize_char = self.config.get('output', {}).get('filename_sanitize_char', '_')
        
        def sanitize(name):
             sanitized = re.sub(r'[<>:"/\\|?*]', sanitize_char, name).strip()
             if len(sanitized) > 100:
                 sanitized = sanitized[:100].strip()
             return sanitized
        
        for res in resource_list:
            if not isinstance(res, dict) or not res.get('data_b64'): continue
            
            try:
                data = base64.b64decode(res['data_b64'])
                md5_hash = hashlib.md5(data).hexdigest()
                
                filename = res.get('filename')
                if not filename:
                    ext = mimetypes.guess_extension(res.get('mime', '')) or '.bin'
                    filename = f"{md5_hash}{ext}"
                
                final_filename = sanitize(filename)
                filename_map[final_filename] = res
                
            except Exception as e:
                logging.warning(f"Error preparing resource for embedding: {e}")

        # Now replace
        for img in soup.find_all('img'):
            src = img.get('src', '')
            if src.startswith('note_contents/'):
                filename = src.split('/')[-1]
                if filename in filename_map:
                    res = filename_map[filename]
                    mime = res.get('mime', 'image/png')
                    
                    # Replace src
                    img['src'] = f"data:{mime};base64,{res['data_b64']}"
                    
                    # Add OCR
                    reco_xml = res.get('recognition')
                    if reco_xml:
                        ocr_text = self._extract_text_from_reco(reco_xml)
                        if ocr_text:
                             # Container logic
                             # Create hidden container for searchability
                             container = soup.new_tag('span')
                             
                             # We need to replace img in DOM, so we copy it or wrap it
                             img.wrap(container)
                             # img is now inside container
                             
                             hidden_div = soup.new_tag('div')
                             hidden_div['style'] = "display:none;" 
                             hidden_div.string = ocr_text
                             container.append(hidden_div)

    def _extract_text_from_reco(self, reco_xml):
        """Extract text content from Evernote recognition XML."""
        try:
             from lxml import etree
             root = etree.fromstring(reco_xml.encode('utf-8'))
             words = []
             for t in root.iter('t'):
                 if t.text:
                     words.append(t.text)
             return " ".join(words)
        except Exception as e:
            logging.warning(f"Failed to parse recognition XML: {e}")
            return None

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
