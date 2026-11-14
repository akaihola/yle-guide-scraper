"""Unit tests for fetch_areena module."""

from __future__ import annotations

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


@pytest.mark.parametrize(
    ("series_id", "build_id", "response_data", "expected_title"),
    [
        (
            "1-1234567",
            "abc123",
            {"pageProps": {"view": {"title": "Test Series"}}},
            "Test Series",
        ),
        (
            "1-7654321",
            "def456",
            {"pageProps": {"view": {}}},  # Missing title
            None,
        ),
        (
            "1-9999999",
            None,  # No build_id
            {},
            None,
        ),
    ],
)
def test_get_series_title(
    series_id: str,
    build_id: str | None,
    response_data: dict,
    expected_title: str | None,
    tmp_path: Path,
) -> None:
    """Test fetching series title from cache or API."""
    from fetch_areena import AreenaCache

    cache = AreenaCache(str(tmp_path))

    with patch("requests.get") as mock_get:
        mock_response = requests.Response()
        mock_response.status_code = 200
        mock_response._content = json.dumps(response_data).encode()  # noqa: SLF001
        mock_get.return_value = mock_response

        # First call should hit the API
        title = cache.get_series_title(series_id, build_id)
        assert title == expected_title

        if build_id:
            mock_get.assert_called_once_with(
                f"https://areena.yle.fi/_next/data/{build_id}/fi/podcastit/{series_id}.json",
                timeout=30,
            )

            # Second call should hit the cache
            mock_get.reset_mock()
            cached_title = cache.get_series_title(series_id, build_id)
            assert cached_title == expected_title
            mock_get.assert_not_called()
        else:
            mock_get.assert_not_called()


@pytest.mark.parametrize(
    ("schedule_data", "expected_id", "expected_name"),
    [
        (
            {
                "meta": {
                    "analytics": {
                        "context": {
                            "comscore": {
                                "yle_referer": (
                                    "radio.guide.2024-01-01.radio_opas.yle_radio_1.untitled_list"
                                ),
                            },
                        },
                    },
                },
            },
            "yle-radio-1",
            "Yle Radio 1",
        ),
        (
            {
                "meta": {
                    "analytics": {
                        "context": {
                            "comscore": {
                                "yle_referer": (
                                    "radio.guide.2024-01-01.radio_opas.some_other_channel.untitled_list"
                                ),
                            },
                        },
                    },
                },
            },
            "some-other-channel",
            "Some Other Channel",
        ),
        (
            # Format used by the API since 2026-02-11
            {
                "meta": {
                    "analytics": {
                        "context": {
                            "yle": {
                                "source_ref": (
                                    "radio.guide.2026-11-14.radio_opas.yle-radio-1.untitled_list"
                                ),
                            },
                        },
                    },
                },
            },
            "yle-radio-1",
            "Yle Radio 1",
        ),
    ],
)
def test_extract_service_info(
    schedule_data: dict,
    expected_id: str,
    expected_name: str,
) -> None:
    """Test extracting service ID and name from schedule data."""
    from fetch_areena import _extract_service_info

    service_id, service_name = _extract_service_info(schedule_data)
    assert service_id == expected_id
    assert service_name == expected_name


@pytest.mark.parametrize(
    "schedule_data",
    [
        {"meta": {"analytics": {"context": {"comscore": {"yle_referer": ""}}}}},
        {"meta": {"analytics": {"context": {"yle": {}}}}},
    ],
)
def test_extract_service_info_missing(schedule_data: dict) -> None:
    """A response without a service ID fails instead of writing outside its folder."""
    from fetch_areena import _extract_service_info

    with pytest.raises(ValueError, match="service ID"):
        _extract_service_info(schedule_data)


def _schedule_item(title: str, start: str, duration_seconds: int) -> dict:
    """Build a schedule card like the ones the Areena API returns."""
    return {
        "title": title,
        "labels": [
            {"type": "broadcastStartDate", "raw": start},
            {"type": "duration", "raw": f"PT{duration_seconds}S"},
        ],
    }


def _schedule_response(items: list[dict]) -> dict:
    return {
        "meta": {
            "analytics": {
                "context": {
                    "yle": {
                        "source_ref": (
                            "radio.guide.2026-11-14.radio_opas.yle-radio-1.untitled_list"
                        ),
                    },
                },
            },
        },
        "data": items,
    }


def test_convert_to_yaml_keeps_overnight_and_skips_availability_window() -> None:
    """Overnight broadcasts are kept; year-long availability windows are dropped."""
    from fetch_areena import convert_to_yaml

    schedule = _schedule_response(
        [
            # Starts the previous evening, as the first item of each day does
            _schedule_item("Yöklassinen", "2026-11-13T23:40:00+02:00", 28200),
            _schedule_item("Yle Uutiset ja sää", "2026-11-14T08:00:00+02:00", 300),
            # Seen in the archive: listed for every day for a whole year
            _schedule_item(
                "Dominante 50 - Juhlakonsertti",
                "2025-11-19T19:02:00+02:00",
                31_640_277,
            ),
        ],
    )

    programmes = convert_to_yaml(schedule)["data"]["Yle Radio 1"]["programmes"]

    assert [(p["title"], p["start_time"], p["end_time"]) for p in programmes] == [
        ("Yöklassinen", "2026-11-13T23:40:00+02:00", "2026-11-14T07:30:00+02:00"),
        (
            "Yle Uutiset ja sää",
            "2026-11-14T08:00:00+02:00",
            "2026-11-14T08:05:00+02:00",
        ),
    ]


def test_fetch_multiple_days_stops_when_only_availability_windows_remain(
    tmp_path: Path,
) -> None:
    """Fetching stops at the first day without broadcasts, even if the API has data."""
    from fetch_areena import AreenaCache, AreenaData, FetchConfig, fetch_multiple_days

    window = _schedule_item("Konsertti", "2026-07-17T11:00:00+03:00", 31_582_740)
    responses = [
        _schedule_response(
            [_schedule_item("Yle Uutiset", "2026-11-14T08:00:00+02:00", 300), window],
        ),
        _schedule_response([window]),
        _schedule_response([window]),
    ]
    config = FetchConfig(
        areena_data=AreenaData(next_data={}, build_id=None, data_hash="hash"),
        output=None,
        directory=str(tmp_path / "yle"),
        cache=AreenaCache(str(tmp_path / "cache")),
    )

    with (
        patch("fetch_areena.fetch_schedule", side_effect=responses) as fetch,
        patch(
            "fetch_areena.datetime",
            wraps=datetime,
        ) as mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(2026, 11, 14, tzinfo=timezone.utc)
        fetch_multiple_days(config)

    assert fetch.call_count == 2  # noqa: PLR2004
    written = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*.yaml"))
    assert written == [Path("yle/yle-radio-1/2026/11/14.yaml")]


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
