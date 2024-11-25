#!/usr/bin/env python3

import contextlib
import json
import logging
import traceback
from datetime import date, datetime
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
    root = ET.Element("ebucore:ebuCoreMain")
    root.set("xmlns:ebucore", "urn:ebu:metadata-schema:ebucore")
    root.set("xmlns:xsi", "http://www.w3.org/2001/XMLSchema-instance")
    root.set("xmlns:dc", "http://purl.org/dc/elements/1.1/")
    root.set("xmlns:dcterms", "http://purl.org/dc/terms/")
    root.set("xmlns:time", "http://www.w3.org/2006/time#")
    root.set(
        "xsi:schemaLocation",
        "urn:ebu:metadata-schema:ebucore https://raw.githubusercontent.com/ebu/ebucore/master/EBUCore.xsd",
    )
    root.set("version", "1.10")
    root.set("dateLastModified", datetime.now().isoformat())

    # Create programmeList element
    programme_list = ET.SubElement(root, "ebucore:programmeList")

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

        programme = ET.SubElement(programme_list, "ebucore:programme")

        # Required programmeId attribute
        programme.set("programmeId", str(item_id))

        # Title (required)
        title_group = ET.SubElement(programme, "ebucore:titleGroup")
        title = ET.SubElement(title_group, "ebucore:title")
        title.text = item["title"]
        title.set("typeLabel", "main")

        # Description group (optional)
        if item.get("description"):
            desc_group = ET.SubElement(programme, "ebucore:descriptionGroup")
            desc = ET.SubElement(desc_group, "ebucore:description")
            desc.text = item["description"]
            desc.set("typeLabel", "main")

        # Timing information
        timing_group = ET.SubElement(programme, "ebucore:timelineGroup")

        # Start time
        start = ET.SubElement(timing_group, "ebucore:publishedStartDateTime")
        start.text = start_time.isoformat()
        start.set("typeLabel", "actual")

        # Extract and format duration
        duration_seconds = 0
        for label in item.get("labels", []):
            if label.get("type") == "duration":
                duration_raw = label.get("raw", "")
                if duration_raw.startswith("PT") and duration_raw.endswith("S"):
                    with contextlib.suppress(ValueError):
                        duration_seconds = int(duration_raw[2:-1])
                break

        duration = ET.SubElement(timing_group, "ebucore:duration")
        duration.set("normalPlayTime", f"PT{duration_seconds}S")
        duration.set("typeLabel", "actual")

        # Service information
        service = ET.SubElement(programme, "ebucore:serviceInformation")
        service_name = ET.SubElement(service, "ebucore:serviceName")
        service_name.text = service_name
        service_name.set("typeLabel", "main")

        # Add required service ID
        service.set("serviceId", service_id)

        # Add publication channel
        channel = ET.SubElement(service, "ebucore:publishingChannel")
        channel.set("typeLabel", "Radio")

    return root


def main() -> None:
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

        # Create the XML string with proper formatting
        ET.indent(ebucore_xml)  # Pretty print the XML
        xml_str = ET.tostring(ebucore_xml, encoding="unicode")

        logging.info("Generated EBUCore Plus XML:\n%s", xml_str)
    except Exception:
        logging.exception("Error occurred:")
        logging.exception(traceback.format_exc())


if __name__ == "__main__":
    main()
