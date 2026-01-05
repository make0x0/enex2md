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
                #'updated': str(note_data.get('updated')), # Optional
                'tags': note_data.get('tags', []),
            }
            if note_data.get('source_url'):
                front_matter['source_url'] = note_data.get('source_url')
                
            if note_data.get('location'):
                front_matter['location'] = note_data.get('location')

            fm_str = yaml.dump(front_matter, allow_unicode=True, default_flow_style=False)
            markdown_text = f"---\n{fm_str}---\n\n{markdown_text}"
            
            # Add location link at the bottom if enabled
            add_loc = self.config.get('content', {}).get('add_location_link', True)
            loc = note_data.get('location', {})
            if add_loc and loc.get('latitude') and loc.get('longitude'):
                 lat = loc['latitude']
                 lon = loc['longitude']
                 map_url = f"https://www.google.com/maps/search/?api=1&query={lat},{lon}"
                 markdown_text += f"\n\n---\n[📍 Location]({map_url})"
            
        output_path = target_dir / "content.md"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(markdown_text)
            
        return output_path
