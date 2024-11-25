#!/usr/bin/env python3

import argparse
import contextlib
import json
import logging
import sys
import traceback
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

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


def convert_to_ebucore(schedule_data):
    """Convert Areena schedule data to EBUCore Plus XML format."""
    # Extract service info from schedule data
    service_id = (
        schedule_data.get("meta", {})
        .get("analytics", {})
        .get("context", {})
        .get("comscore", {})
        .get("yle_referer", "")
        .split(".")[-2]
    )
    # Convert yle_radio_1 to yle-radio-1 format
    service_id = service_id.replace("_", "-")

    # Map service IDs to human readable names
    service_names = {"yle-radio-1": "Yle Radio 1"}
    service_name = service_names.get(service_id, service_id.replace("-", " ").title())

    # Create root element with namespaces
    root = ET.Element("ec:ebuCoreMain")
    root.set("xmlns:ec", "urn:ebu:metadata-schema:ebucore")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance") 
    root.set("xmlns:dc", "http://purl.org/dc/elements/1.1/")
    root.set("xmlns:rdf", "http://www.w3.org/1999/02/22-rdf-syntax-ns#")
    root.set("xmlns:dcterms", "http://purl.org/dc/terms/")
    root.set("xmlns:time", "http://www.w3.org/2006/time#")
    root.set(
        "xsi:schemaLocation",
        "urn:ebu:metadata-schema:ebucore https://raw.githubusercontent.com/ebu/ebucore/master/EBUCore.xsd",
    )
    root.set("version", "1.10")
    root.set("dateLastModified", datetime.now().isoformat())

    # Create service definition
    services = ET.SubElement(root, "ec:serviceList")
    service = ET.SubElement(services, "ec:service")
    service.set("serviceId", service_id)
    
    service_name_elem = ET.SubElement(service, "ec:serviceName")
    service_name_elem.text = service_name
    service_name_elem.set("typeLabel", "main")
    
    channel = ET.SubElement(service, "ec:publishingChannel")
    channel.set("typeLabel", "Radio")

    # Create programmeList element
    programme_list = ET.SubElement(root, "ec:programmeList")

    # Convert each schedule item
    for item in schedule_data.get("data", []):
        # Skip items missing required fields
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

        # Generate an ID if missing
        item_id = (
            item.get("id") or item.get("pointer", {}).get("uri", "").split("/")[-1]
        )
        if not item_id:
            logging.warning(f"Skipping item due to missing ID: {item}")
            continue

        programme = ET.SubElement(programme_list, "ec:programme")

        # Required programmeId attribute
        programme.set("programmeId", str(item_id))

        # Title (required)
        title_group = ET.SubElement(programme, "ec:titleGroup")
        title = ET.SubElement(title_group, "ec:title")
        title.text = item["title"]
        title.set("typeLabel", "main")

        # Description group (optional)
        if item.get("description"):
            desc_group = ET.SubElement(programme, "ec:descriptionGroup")
            desc = ET.SubElement(desc_group, "ec:description")
            desc.text = item["description"]
            desc.set("typeLabel", "main")

        # Timing information
        timing_group = ET.SubElement(programme, "ec:timelineGroup")

        # Start and end times
        # Extract duration once
        duration_seconds = 0
        for label in item.get("labels", []):
            if label.get("type") == "duration":
                duration_raw = label.get("raw", "")
                if duration_raw.startswith("PT") and duration_raw.endswith("S"):
                    with contextlib.suppress(ValueError):
                        duration_seconds = int(duration_raw[2:-1])
                break

        # Create timing elements in a specific order with proper RDF structure
        if start_time:
            # Create a container for start time
            start_container = ET.SubElement(timing_group, "ec:publishedStartDateTime")
            start_container.text = start_time.isoformat()
            start_container.set("typeLabel", "actual")

        if duration_seconds > 0:
            # Create duration using normalPlayTime
            if duration_seconds > 0:
                duration = ET.SubElement(timing_group, "ec:duration")
                normal_play_time = ET.SubElement(duration, "ec:normalPlayTime")
                normal_play_time.text = f"PT{duration_seconds}S"

            # Calculate and create end time only if we have duration
            end_time = start_time + timedelta(seconds=duration_seconds)
            end_container = ET.SubElement(timing_group, "ec:publishedEndDateTime")
            end_container.text = end_time.isoformat()
            end_container.set("typeLabel", "actual")

        # Reference the service
        service_ref = ET.SubElement(programme, "ec:serviceInformation")
        service_ref.set("serviceId", service_id)

    return root


def write_xml(xml_root, output_file=None):
    """Write XML to file or stdout."""
    ET.indent(xml_root)  # Pretty print the XML
    xml_str = ET.tostring(xml_root, encoding="unicode")
    
    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(xml_str)
        logging.info(f"XML written to: {output_file}")
    else:
        print(xml_str)

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

        # Convert to EBUCore Plus format
        ebucore_xml = convert_to_ebucore(schedule_data)

        # Write XML to file or stdout
        write_xml(ebucore_xml, args.output)

    except Exception:
        logging.exception("Error occurred:")
        logging.exception(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
