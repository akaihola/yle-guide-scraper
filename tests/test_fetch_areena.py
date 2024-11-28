"""Unit tests for fetch_areena module."""

import json
from pathlib import Path
from unittest.mock import patch

import requests

from fetch_areena import get_next_data

TESTS_DIR = Path(__file__).parent
DATA_DIR = TESTS_DIR / "data"
SHA256_LENGTH = 64  # Number of characters in a SHA-256 hash


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
