---
name: yle-areena-schedule-api
description: Diagnose or adapt the scraper when the Yle Areena radio schedule API changes, and check that the saved schedule files contain real broadcasts.
---

# Yle Areena schedule API

Verified 2026-11-14 against the live API, unless marked otherwise.

## Output layout

- Radio 1 schedules belong under `yle/yle-radio-1/YYYY/MM/DD.yaml`, with the
  service key `Yle Radio 1`. Antti chose this layout (2026-11-14) so other
  channels can use sibling directories later. The
  [weekly guide](https://github.com/akaihola/yle-weekly-guide) reads it.
- A file directly under `yle/YYYY/` with an `''` service key means the scraper
  could not find the service ID. The scraper now fails instead of writing it.

## Schedule endpoint

- `https://areena.api.yle.fi/v1/ui/schedules/<channel>/<YYYY-MM-DD>.json` with
  the `language`, `v`, `client`, `app_id`, `app_key` and `yleReferer` query
  parameters built by [`build_api_url`](../../../fetch_areena.py). The
  [web guide](https://areena.yle.fi/podcastit/opas) renders in the browser from
  the same endpoint, so its HTML holds no schedule to compare against.
- Each item in `data` has labels `broadcastStartDate`, `broadcastEndDate` and
  `duration` (`PT<seconds>S`). The first item of a day usually starts the
  previous evening: Yöklassinen at 23:40, or at 00:00. That is a normal
  overnight broadcast, not an error.
- On 2026-11-14 the API returned real schedules for 35 days ahead and an empty
  `data` list after that.

## Changes seen

- **2026-02-11, referer field moved.** The referer string
  `radio.guide.<date>.radio_opas.<service>.untitled_list` moved from
  `meta.analytics.context.comscore.yle_referer` to
  `meta.analytics.context.yle.source_ref`. Until 2026-11-14 the scraper wrote
  everything to `yle/YYYY/…` with an empty service key. The data history was
  rewritten so those files sit in `yle/yle-radio-1/…`, with the original commit
  dates.
- **Availability windows (seen 2025-11 and 2026-06).** For some days after the
  real schedule, the API returned a single on-demand item whose start and end
  span a whole year: "Dominante 50 - Juhlakonsertti" from 2025-11-19 to
  2026-11-19, and "Maisteri Lindgrenin musiikkiesitelmä" from 2026-07-17 to
  2027-07-16. They are not broadcasts. The scraper drops items longer than
  24 hours and stops at the first day without real broadcasts. The longest real
  broadcast in the archive is 9 h 15 min.

## Checking real data

- Do not judge correctness from file or row counts. Compare a few programmes'
  start times with their item pages: `https://areena.yle.fi/podcastit/<item id>`
  (the id is in the item's `pointer.uri`) embeds the same broadcast start time
  in its `__NEXT_DATA__`. Three items matched this way on 2026-11-14.
- For a trial, run `uv run fetch_areena.py -d <tmp>/yle -c <tmp>/cache`, then
  the guide's `schedule_analyzer.py -d <tmp>/yle/yle-radio-1` from a temporary
  directory. HTML output copies static files into the current directory.
