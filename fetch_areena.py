#!/usr/bin/env python3

import json
import requests
from bs4 import BeautifulSoup
from datetime import date
from urllib.parse import urlencode

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

def main():
    try:
        next_data = get_next_data()
        api_url = build_api_url(next_data)
        print(f"Generated API URL:\n{api_url}")
        
        schedule_data = fetch_schedule(api_url)
        print("\nSchedule data:")
        print(json.dumps(schedule_data, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
