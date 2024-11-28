"""Unit tests for fetch_areena module."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from fetch_areena import get_next_data

TESTS_DIR = Path(__file__).parent
DATA_DIR = TESTS_DIR / "data"
SHA256_LENGTH = 64  # Number of characters in a SHA-256 hash


@pytest.mark.parametrize(
    ("next_data", "date", "expected_url"),
    [
        (
            {
                "locale": "fi",
                "runtimeConfig": {
                    "appIdFrontend": "test-app-id",
                    "appKeyFrontend": "test-app-key",
                },
                "props": {
                    "pageProps": {
                        "view": {
                            "tabs": [
                                {
                                    "content": [
                                        {"source": {"uri": "https://example.com?v=10"}},
                                    ],
                                },
                            ],
                        },
                    },
                },
            },
            datetime(2024, 1, 1, tzinfo=timezone.utc),
            "https://areena.api.yle.fi/v1/ui/schedules/yle-radio-1/2024-01-01.json?"
            "language=fi&v=10&client=yle-areena-web&app_id=test-app-id&"
            "app_key=test-app-key&yleReferer=radio.guide.2024-01-01.radio_opas.yle-radio-1.untitled_list",
        ),
        (
            {
                "locale": "sv",
                "runtimeConfig": {
                    "appIdFrontend": "other-app-id",
                    "appKeyFrontend": "other-app-key",
                },
                "props": {
                    "pageProps": {
                        "view": {
                            "tabs": [
                                {
                                    "content": [
                                        {"source": {"uri": "https://example.com?v=11"}},
                                    ],
                                },
                            ],
                        },
                    },
                },
            },
            datetime(2024, 12, 31, tzinfo=timezone.utc),
            "https://areena.api.yle.fi/v1/ui/schedules/yle-radio-1/2024-12-31.json?"
            "language=sv&v=11&client=yle-areena-web&app_id=other-app-id&"
            "app_key=other-app-key&yleReferer=radio.guide.2024-12-31.radio_opas.yle-radio-1.untitled_list",
        ),
    ],
)
def test_build_api_url(next_data: dict, date: datetime, expected_url: str) -> None:
    """Test building API URL with different input data."""
    from fetch_areena import build_api_url

    url = build_api_url(next_data, date)
    assert url == expected_url


def test_get_next_data() -> None:
    """Test extracting __NEXT_DATA__ from Areena podcast guide."""
    # Load test data
    with (DATA_DIR / "areena_opas.html").open("r", encoding="utf-8") as f:
        html_content = f.read()

    with (DATA_DIR / "areena_opas.json").open("r", encoding="utf-8") as f:
        expected_data = json.load(f)

    # Mock the HTTP request
    with patch("requests.get") as mock_get:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = html_content.encode()  # noqa: SLF001
        mock_get.return_value = mock_response

        # Call the function
        data, build_id, data_hash = get_next_data()

        # Verify the mock was called correctly
        mock_get.assert_called_once_with(
            "https://areena.yle.fi/podcastit/opas",
            timeout=30,
        )

        # Check the results
        assert data == expected_data
        assert build_id == expected_data.get("buildId")
        assert len(data_hash) == SHA256_LENGTH
