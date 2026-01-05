from markdownify import markdownify as md
import yaml

class MarkdownFormatter:
    def __init__(self, config):
        self.config = config
        self.add_front_matter = config.get('markdown', {}).get('add_front_matter', True)
        self.heading_style = config.get('markdown', {}).get('heading_style', 'atx')

    def generate(self, target_dir, intermediate_html, title, note_data):
        # Convert HTML to Markdown
        # Customize markdownify options if needed (e.g. heading_style)
        markdown_text = md(intermediate_html, heading_style=self.heading_style)
        
        # Add Front Matter if requested
        if self.add_front_matter:
            front_matter = {
                'title': title,
                'created': str(note_data.get('created')),
            if note_data.get('updated'):
                 front_matter['updated'] = str(note_data.get('updated'))

            if note_data.get('location'):
                front_matter['location'] = note_data.get('location')

            fm_str = yaml.dump(front_matter, allow_unicode=True, default_flow_style=False)
            markdown_text = f"---\n{fm_str}---\n\n{markdown_text}"
            
            # Append Metadata to Body for visibility
            markdown_text += "\n\n---\n"
            if note_data.get('tags'):
                markdown_text += f"\n**Tags**: {', '.join(note_data.get('tags'))}"
            
            if note_data.get('source_url'):
                markdown_text += f"\n**Source**: [{note_data.get('source_url')}]({note_data.get('source_url')})"

            # Add location link at the bottom if enabled
            add_loc = self.config.get('content', {}).get('add_location_link', True)
            loc = note_data.get('location', {})
            if add_loc and loc.get('latitude') and loc.get('longitude'):
                 lat = loc['latitude']
                 lon = loc['longitude']
                 
                 # Reverse Geocoding
                 loc_name = ""
                 try:
                    import reverse_geocoder as rg
                    results = rg.search((lat, lon))
                    if results:
                        r = results[0]
                        loc_name = f"{r.get('name', '')}, {r.get('cc', '')}"
                 except ImportError:
                     pass
                 except Exception:
                     pass # Silently fail in markdown generation keys
                     
                 display_text = f"📍 Location: {loc_name} ({lat:.4f}, {lon:.4f})" if loc_name else f"📍 Location ({lat:.4f}, {lon:.4f})"
                 map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                 markdown_text += f"\n[{display_text}]({map_url})"
            
        output_path = target_dir / "content.md"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
            
        return output_path
