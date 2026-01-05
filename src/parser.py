from lxml import etree
from datetime import datetime
import dateutil.parser
import logging

class NoteParser:
    def __init__(self, file_path):
        self.file_path = file_path

    def parse(self):
        """Yields note data dictionaries from the ENEX file."""
        context = etree.iterparse(str(self.file_path), events=('end',), tag='note', huge_tree=True)
        
        for event, elem in context:
            note_data = self._extract_note_data(elem)
            yield note_data
            # Clear element to save memory
            elem.clear()
            while elem.getprevious() is not None:
                del elem.getparent()[0]
        del context

    def _extract_note_data(self, note_elem):
        title = note_elem.findtext('title')
        content = note_elem.findtext('content')
        created = note_elem.findtext('created')
        updated = note_elem.findtext('updated')
        
        tags = [tag.text for tag in note_elem.findall('tag')]
        
        resources = []
        for res_elem in note_elem.findall('resource'):
            res_data = self._extract_resource_data(res_elem)
            if res_data:
                resources.append(res_data)

        # Parse dates
        created_dt = self._parse_date(created)
        updated_dt = self._parse_date(updated)

        # Handle attributes like source-url if needed (often in note-attributes)
        source_url = None
        location = {}
        attr_elem = note_elem.find('note-attributes')
        if attr_elem is not None:
            source_url = attr_elem.findtext('source-url')
            lat_str = attr_elem.findtext('latitude')
            lon_str = attr_elem.findtext('longitude')
            if lat_str and lon_str:
                try:
                    location['latitude'] = float(lat_str)
                    location['longitude'] = float(lon_str)
                except ValueError:
                    pass

        return {
            'title': title,
            'content': content,
            'created': created_dt,
            'updated': updated_dt,
            'tags': tags,
            'resources': resources,
            'source_url': source_url,
            'location': location
        }

    def _extract_resource_data(self, res_elem):
        data_elem = res_elem.find('data')
        if data_elem is None or not data_elem.text:
            return None
            
        b64_data = data_elem.text.strip()
        mime_elem = res_elem.find('mime')
        mime = mime_elem.text if mime_elem is not None else 'application/octet-stream'
        
        filename = None
        res_attr = res_elem.find('resource-attributes')
        if res_attr is not None:
            filename = res_attr.findtext('file-name')
            
        # If no filename, maybe try to guess extension from mime later
        
        recognition = None
        reco_elem = res_elem.find('recognition')
        
        # Debug logging to investigate missing recognition
        # Log all children tags to see what's actually there
        # resource_children = [child.tag for child in res_elem]
        # logging.info(f"Resource children: {resource_children}")
        
        if reco_elem is not None:
            if reco_elem.text:
                recognition = reco_elem.text.strip()
            else:
                 logging.warning("Found <recognition> tag but it was empty.")
        else:
            # Check if it exists with namespace?
            # logging.info("No <recognition> tag found in this resource.")
            pass
            
        return {
            'data_b64': b64_data,
            'mime': mime,
            'filename': filename,
            'recognition': recognition
        }

    def _parse_date(self, date_str):
        if not date_str:
            return None
        # ENEX dates are usually ISO 8601 like 20230101T120000Z
        try:
            return dateutil.parser.parse(date_str)
        except:
            return None
