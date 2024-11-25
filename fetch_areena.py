#!/usr/bin/env python3

import json
import requests
import traceback
from bs4 import BeautifulSoup
from datetime import date, datetime
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

def get_next_data():
    """Fetch and extract __NEXT_DATA__ JSON from Areena podcast guide"""
    url = "https://areena.yle.fi/podcastit/opas"
    response = requests.get(url)
    response.raise_for_status()
    
    soup = BeautifulSoup(response.text, 'html.parser')
    next_data = soup.find('script', id='__NEXT_DATA__')
    
    if not next_data:
        raise ValueError("Could not find __NEXT_DATA__ script tag")
        
    return json.loads(next_data.string)

def build_api_url(next_data):
    """Build Areena API URL using parameters from __NEXT_DATA__"""
    # Extract needed values from next_data
    props = next_data.get('props', {}).get('pageProps', {})
    
    # Extract parameters from next_data
    # Extract API version from the first API URL in the view content
    view = next_data.get('props', {}).get('pageProps', {}).get('view', {})
    first_uri = None
    for tab in view.get('tabs', []):
        for content in tab.get('content', []):
            if 'source' in content and 'uri' in content['source']:
                first_uri = content['source']['uri']
                break
        if first_uri:
            break

    # Parse v parameter from the URI
    from urllib.parse import parse_qs, urlparse
    v = '10'  # Default value
    if first_uri:
        query = parse_qs(urlparse(first_uri).query)
        if 'v' in query:
            v = query['v'][0]

    runtime_config = next_data.get('runtimeConfig', {})
    params = {
        'language': next_data.get('locale', 'fi'),
        'v': v,
        'client': 'yle-areena-web',
        'app_id': runtime_config.get('appIdFrontend', 'areena-web-items'),
        'app_key': runtime_config.get('appKeyFrontend', 'wlTs5D9OjIdeS9krPzRQR4I1PYVzoazN')
    }
    
    # Add date-specific parameters
    today = date.today().isoformat()
    channel = 'yle-radio-1'  # This could be extracted from next_data if needed
    
    params['yleReferer'] = f'radio.guide.{today}.radio_opas.{channel}.untitled_list'
    
    # Construct the final URL
    base_url = f'https://areena.api.yle.fi/v1/ui/schedules/{channel}/{today}.json'
    return f"{base_url}?{urlencode(params)}"

def fetch_schedule(url):
    """Fetch schedule data from the Areena API"""
    response = requests.get(url)
    response.raise_for_status()
    return response.json()

def convert_to_ebucore(schedule_data):
    """Convert Areena schedule data to EBUCore Plus XML format"""
    # Create root element with namespaces
    root = ET.Element('ebucore:ebuCoreMain')
    root.set('xmlns:ebucore', 'urn:ebu:metadata-schema:ebucore')
    root.set('xmlns:xsi', 'http://www.w3.org/2001/XMLSchema-instance')
    root.set('xsi:schemaLocation', 'urn:ebu:metadata-schema:ebucore https://raw.githubusercontent.com/ebu/ebucore/master/EBUCore.xsd')
    
    # Create programmeList element
    programme_list = ET.SubElement(root, 'ebucore:programmeList')
    
    # Convert each schedule item
    for item in schedule_data.get('data', []):
        # Skip items missing required fields
        if not all(key in item and item[key] for key in ['title']):
            print(f"Skipping item due to missing required fields: {item}")
            continue

        # Extract startTime from labels
        start_time = None
        for label in item.get('labels', []):
            if label.get('type') == 'broadcastStartDate':
                try:
                    start_time = datetime.fromisoformat(label.get('raw', ''))
                    break
                except ValueError:
                    pass

        if not start_time:
            print(f"Skipping item due to missing startTime in labels: {item}")
            continue
            
        # Generate an ID if missing
        item_id = item.get('id') or item.get('pointer', {}).get('uri', '').split('/')[-1]
        if not item_id:
            print(f"Skipping item due to missing ID: {item}")
            continue
            
        programme = ET.SubElement(programme_list, 'ebucore:programme')
        
        # Programme ID
        programme.set('programmeId', str(item_id))
        
        # Title
        title = ET.SubElement(programme, 'ebucore:title')
        title.text = item['title']
        
        # Description (optional)
        if item.get('description'):
            desc = ET.SubElement(programme, 'ebucore:description')
            desc.text = item['description']
        
        # Timing information
        timing = ET.SubElement(programme, 'ebucore:publishedStartDateTime')
        timing.text = start_time.isoformat()
        
        # Extract duration from labels
        duration_seconds = 0
        for label in item.get('labels', []):
            if label.get('type') == 'duration':
                duration_raw = label.get('raw', '')
                if duration_raw.startswith('PT') and duration_raw.endswith('S'):
                    try:
                        duration_seconds = int(duration_raw[2:-1])  # Remove 'PT' and 'S'
                    except ValueError:
                        pass
                break

        duration = ET.SubElement(programme, 'ebucore:duration')
        duration.text = str(duration_seconds)
        
        # Service information
        service = ET.SubElement(programme, 'ebucore:serviceInformation')
        service_name = ET.SubElement(service, 'ebucore:serviceName')
        service_name.text = 'Yle Radio 1'
        
    return root

def main():
    try:
        next_data = get_next_data()
        api_url = build_api_url(next_data)
        print(f"Generated API URL:\n{api_url}")
        
        schedule_data = fetch_schedule(api_url)
        
        # Convert to EBUCore Plus format
        ebucore_xml = convert_to_ebucore(schedule_data)
        
        # Create the XML string with proper formatting
        ET.indent(ebucore_xml)  # Pretty print the XML
        xml_str = ET.tostring(ebucore_xml, encoding='unicode')
        
        print("\nEBUCore Plus XML:")
        print(xml_str)
    except Exception as e:
        print("Error occurred:")
        print(traceback.format_exc())

if __name__ == "__main__":
    main()
