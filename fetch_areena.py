#!/usr/bin/env python3
"""Fetch and convert Yle Areena radio schedule data to YAML format."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import git
import requests
from bs4 import BeautifulSoup
from diskcache import Cache
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import PreservedScalarString


def get_next_data() -> tuple[dict, str | None]:
    """Fetch and extract __NEXT_DATA__ JSON from Areena podcast guide."""
    url = "https://areena.yle.fi/podcastit/opas"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    next_data = soup.find("script", id="__NEXT_DATA__")

    if not next_data:
        msg = "Could not find __NEXT_DATA__ script tag"
        raise ValueError(msg)

    data = json.loads(next_data.string)
    return data, data.get("buildId")


def build_api_url(next_data: dict) -> str:
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
    today = datetime.now(tz=timezone.utc).date().isoformat()
    channel = "yle-radio-1"  # This could be extracted from next_data if needed

    params["yleReferer"] = f"radio.guide.{today}.radio_opas.{channel}.untitled_list"

    # Construct the final URL
    base_url = f"https://areena.api.yle.fi/v1/ui/schedules/{channel}/{today}.json"
    return f"{base_url}?{urlencode(params)}"


def fetch_schedule(url: str) -> dict:
    """Fetch schedule data from the Areena API."""
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


# Initialize disk cache
cache = Cache("~/.cache/areena")


def get_series_title(series_id: str, build_id: str | None) -> str | None:
    """Fetch series title from Areena API."""
    if not build_id:
        return None

    # Create cache key
    cache_key = f"series_title:{series_id}:{build_id}"

    # Try to get from cache first
    cached_title = cache.get(cache_key)
    if cached_title is not None:
        return cached_title

    url = f"https://areena.yle.fi/_next/data/{build_id}/fi/podcastit/{series_id}.json"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        title = data.get("pageProps", {}).get("view", {}).get("title")
        if title:
            # Cache the result for 24 hours
            cache.set(cache_key, title, expire=24 * 60 * 60)
            return title
        return None
    except (requests.RequestException, KeyError, json.JSONDecodeError):
        logging.warning("Failed to fetch series title for %s", series_id)
        return None


def _extract_service_info(schedule_data: dict) -> tuple[str, str]:
    """Extract service ID and name from schedule data."""
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
    return service_id, service_name


def _extract_time_info(item: dict) -> tuple[datetime | None, datetime | None]:
    """Extract start time and end time from schedule item."""
    start_time = None
    for label in item.get("labels", []):
        if label.get("type") == "broadcastStartDate":
            try:
                start_time = datetime.fromisoformat(label.get("raw", ""))
                break
            except ValueError:
                pass

    duration_seconds = 0
    for label in item.get("labels", []):
        if label.get("type") == "duration":
            duration_raw = label.get("raw", "")
            if duration_raw.startswith("PT") and duration_raw.endswith("S"):
                with contextlib.suppress(ValueError):
                    duration_seconds = int(duration_raw[2:-1])
                break

    end_time = (
        start_time + timedelta(seconds=duration_seconds)
        if start_time and duration_seconds > 0
        else None
    )

    return start_time, end_time


def _extract_series_info(item: dict, build_id: str | None) -> str | None:
    """Extract series information from schedule item."""
    for label in item.get("labels", []):
        if label.get("type") == "seriesLink":
            uri = label.get("pointer", {}).get("uri", "")
            match = re.search(r"yleareena://items/(\d+-\d+)", uri)
            if match:
                series_id = match.group(1)
                return get_series_title(series_id, build_id)
    return None


def get_git_info() -> dict:
    """Get Git repository metadata."""
    try:
        repo = git.Repo(search_parent_directories=True)
        return {
            "branch": repo.active_branch.name,
            "commit": repo.head.commit.hexsha,
        }
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return {}


def convert_to_yaml(schedule_data: dict, build_id: str | None = None) -> dict:
    """Convert Areena schedule data to simple YAML format."""
    service_id, service_name = _extract_service_info(schedule_data)

    yaml_data = {
        "metadata": {
            "generated_at": datetime.now(tz=timezone.utc).isoformat(),
            "git": get_git_info(),
        },
        "data": {
            service_name: {
                "programmes": [],
            },
        },
    }

    for item in schedule_data.get("data", []):
        if not all(key in item and item[key] for key in ["title"]):
            logging.warning("Skipping item due to missing required fields: %s", item)
            continue

        start_time, end_time = _extract_time_info(item)

        if not start_time:
            logging.warning(
                "Skipping item due to missing startTime in labels: %s",
                item,
            )
            continue

        programme = {
            "title": item["title"],
            "start_time": start_time.isoformat(),
        }

        if end_time:
            programme["end_time"] = end_time.isoformat()

        if item.get("description"):
            programme["description"] = item["description"]

        series_title = _extract_series_info(item, build_id)
        if series_title:
            programme["series"] = series_title

        yaml_data["data"][service_name]["programmes"].append(programme)

    return yaml_data


def write_yaml(
    yaml_data: dict,
    output_file: str | None = None,
    directory: str | None = None,
) -> None:
    """Write YAML to file or stdout.

    If directory is provided, saves files as:
    <directory>/<service_id>/<year>/<month>/<day>.yaml
    """
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096  # Prevent line wrapping
    yaml.indent(mapping=2, sequence=4, offset=2)

    # Force description to be literal block style
    for service in yaml_data["data"].values():
        for prog in service["programmes"]:
            if "description" in prog:
                prog["description"] = PreservedScalarString(prog["description"])

    if directory:
        # Get current date components
        now = datetime.now(tz=timezone.utc)

        # Write a file for each service
        for service_name, service_data in yaml_data["data"].items():
            # Convert service name to id format (e.g. "Yle Radio 1" -> "yle-radio-1")
            service_id = service_name.lower().replace(" ", "-")

            # Create directory structure
            output_dir = (
                Path(directory) / service_id / str(now.year) / f"{now.month:02d}"
            )
            output_dir.mkdir(parents=True, exist_ok=True)

            # Create output file
            output_path = output_dir / f"{now.day:02d}.yaml"

            # Create service-specific YAML data
            service_yaml = {
                "metadata": yaml_data["metadata"],
                "data": {service_name: service_data},
            }

            with output_path.open("w", encoding="utf-8") as f:
                yaml.dump(service_yaml, f)
            logging.info("YAML written to: %s", output_path)
    elif output_file:
        with Path(output_file).open("w", encoding="utf-8") as f:
            yaml.dump(yaml_data, f)
        logging.info("YAML written to: %s", output_file)
    else:
        yaml.dump(yaml_data, sys.stdout)


def main() -> None:
    """Execute the main program flow."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Fetch Areena schedule and convert to EBUCore Plus XML",
    )
    parser.add_argument("-o", "--output", help="Output file path (default: stdout)")
    parser.add_argument(
        "-d",
        "--directory",
        help="Directory to save YAML files in format: "
        "<PATH>/<service_id>/<year>/<month>/<day>.yaml",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    try:
        next_data, build_id = get_next_data()
        api_url = build_api_url(next_data)
        logging.info("Generated API URL:\n%s", api_url)

        schedule_data = fetch_schedule(api_url)

        # Convert to YAML format
        yaml_data = convert_to_yaml(schedule_data, build_id)

        # Write YAML to file or stdout
        write_yaml(yaml_data, args.output, args.directory)

    except Exception:
        logging.exception("Error occurred:")
        logging.exception(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
