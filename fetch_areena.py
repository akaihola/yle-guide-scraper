#!/usr/bin/env python3

import argparse
import contextlib
import json
import logging
import sys
import traceback
from ruamel.yaml.scalarstring import PreservedScalarString
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from ruamel.yaml import YAML
import requests
from bs4 import BeautifulSoup


def get_next_data():
    """Fetch and extract __NEXT_DATA__ JSON from Areena podcast guide."""
    url = "https://areena.yle.fi/podcastit/opas"
    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")

    if not next_data:
        msg = "Could not find __NEXT_DATA__ script tag"
        raise ValueError(msg)

    return json.loads(next_data.string)


def build_api_url(next_data) -> str:
    """Build Areena API URL using parameters from __NEXT_DATA__."""
    # Extract needed values from next_data
    next_data.get("props", {}).get("pageProps", {})

    # Extract parameters from next_data
    # Extract API version from the first API URL in the view content
    view = next_data.get("props", {}).get("pageProps", {}).get("view", {})
    first_uri = None
    for tab in view.get("tabs", []):
        for content in tab.get("content", []):
            if "source" in content and "uri" in content["source"]:
                first_uri = content["source"]["uri"]
                break
        if first_uri:
            break

    # Parse v parameter from the URI
    from urllib.parse import parse_qs, urlparse

    v = "10"  # Default value
    if first_uri:
        query = parse_qs(urlparse(first_uri).query)
        if "v" in query:
            v = query["v"][0]

    runtime_config = next_data.get("runtimeConfig", {})
    params = {
        "language": next_data.get("locale", "fi"),
        "v": v,
        "client": "yle-areena-web",
        "app_id": runtime_config.get("appIdFrontend", "areena-web-items"),
        "app_key": runtime_config.get(
            "appKeyFrontend",
            "wlTs5D9OjIdeS9krPzRQR4I1PYVzoazN",
        ),
    }

    # Add date-specific parameters
    today = date.today().isoformat()
    channel = "yle-radio-1"  # This could be extracted from next_data if needed

    params["yleReferer"] = f"radio.guide.{today}.radio_opas.{channel}.untitled_list"

    # Construct the final URL
    base_url = f"https://areena.api.yle.fi/v1/ui/schedules/{channel}/{today}.json"
    return f"{base_url}?{urlencode(params)}"


def fetch_schedule(url):
    """Fetch schedule data from the Areena API."""
    response = requests.get(url)
    response.raise_for_status()
    return response.json()


def convert_to_yaml(schedule_data):
    """Convert Areena schedule data to simple YAML format."""
    # Extract service info from schedule data
    service_id = (
        schedule_data.get("meta", {})
        .get("analytics", {})
        .get("context", {})
        .get("comscore", {})
        .get("yle_referer", "")
        .split(".")[-2]
    )
    service_id = service_id.replace("_", "-")

    # Map service IDs to human readable names
    service_names = {"yle-radio-1": "Yle Radio 1"}
    service_name = service_names.get(service_id, service_id.replace("-", " ").title())

    # Prepare YAML structure
    yaml_data = {
        service_name: {
            "programmes": []
        }
    }

    # Convert each schedule item
    for item in schedule_data.get("data", []):
        if not all(key in item and item[key] for key in ["title"]):
            logging.warning(f"Skipping item due to missing required fields: {item}")
            continue

        # Extract startTime from labels
        start_time = None
        for label in item.get("labels", []):
            if label.get("type") == "broadcastStartDate":
                try:
                    start_time = datetime.fromisoformat(label.get("raw", ""))
                    break
                except ValueError:
                    pass

        if not start_time:
            logging.warning(f"Skipping item due to missing startTime in labels: {item}")
            continue

        # Extract duration and calculate end time
        duration_seconds = 0
        for label in item.get("labels", []):
            if label.get("type") == "duration":
                duration_raw = label.get("raw", "")
                if duration_raw.startswith("PT") and duration_raw.endswith("S"):
                    with contextlib.suppress(ValueError):
                        duration_seconds = int(duration_raw[2:-1])
                break

        end_time = start_time + timedelta(seconds=duration_seconds) if duration_seconds > 0 else None

        programme = {
            "title": item["title"],
            "start_time": start_time.isoformat(),
        }
        
        if end_time:
            programme["end_time"] = end_time.isoformat()
        
        if item.get("description"):
            programme["description"] = item["description"]

        yaml_data[service_name]["programmes"].append(programme)

    return yaml_data


def write_yaml(yaml_data, output_file=None):
    """Write YAML to file or stdout."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # Prevent line wrapping
    yaml.indent(mapping=2, sequence=4, offset=2)
    
    # Force description to be literal block style
    for service in yaml_data.values():
        for prog in service['programmes']:
            if 'description' in prog:
                prog['description'] = yaml.scalarstring.PreservedScalarString(prog['description'])
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f)
        logging.info(f"YAML written to: {output_file}")
    else:
        yaml.dump(yaml_data, sys.stdout)

def main() -> None:
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Fetch Areena schedule and convert to EBUCore Plus XML')
    parser.add_argument('-o', '--output', help='Output file path (default: stdout)')
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    try:
        next_data = get_next_data()
        api_url = build_api_url(next_data)
        logging.info(f"Generated API URL:\n{api_url}")

        schedule_data = fetch_schedule(api_url)

        # Convert to YAML format
        yaml_data = convert_to_yaml(schedule_data)

        # Write YAML to file or stdout
        write_yaml(yaml_data, args.output)

    except Exception:
        logging.exception("Error occurred:")
        logging.exception(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
