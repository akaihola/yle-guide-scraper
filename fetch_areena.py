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
    
    # Base parameters that seem to be constant
    params = {
        'language': 'fi',
        'v': '10',
        'client': 'yle-areena-web',
        'offset': '0',
        'limit': '100',
        'country': 'FI',
        'isPortabilityRegion': 'true',
        'app_id': 'areena-web-items',
        'app_key': 'wlTs5D9OjIdeS9krPzRQR4I1PYVzoazN'
    }
    
    # Add date-specific parameters
    today = date.today().isoformat()
    channel = 'yle-radio-1'  # This could be extracted from next_data if needed
    
    params['yleReferer'] = f'radio.guide.{today}.radio_opas.{channel}.untitled_list'
    
    # Construct the final URL
    base_url = f'https://areena.api.yle.fi/v1/ui/schedules/{channel}/{today}.json'
    return f"{base_url}?{urlencode(params)}"

def main():
    try:
        next_data = get_next_data()
        api_url = build_api_url(next_data)
        print(f"Generated API URL:\n{api_url}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
