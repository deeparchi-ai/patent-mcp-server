"""Legal status extraction from Google Patents web page (free)."""

from __future__ import annotations

import logging
import re
from typing import Any

import requests

from web.google_patents import (
    GOOGLE_PATENTS_URL,
    HEADERS,
    TIMEOUT,
    _MetaParser,
)

logger = logging.getLogger(__name__)


def get_legal_status(publication_number: str) -> dict[str, Any]:
    """Extract legal status indicators from Google Patents page metadata.

    Returns:
        dict with keys:
          - publication_number
          - status: 'granted' | 'application' | 'utility_model' | 'unknown'
          - kind_code: A/B/U for CN; A1/B1 for US
          - filing_date, grant_date, priority_date (ISO date strings or None)
          - assignee
          - events: list of legal events with dates from the page
    """
    pub_clean = publication_number.replace("-", "")
    url = GOOGLE_PATENTS_URL.format(pub=pub_clean)

    logger.info("Fetching legal status from %s", url)
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    html = resp.text

    # Parse meta tags for dates
    meta_parser = _MetaParser()
    meta_parser.feed(html)
    meta = meta_parser.meta

    # Extract dates from DC.date
    from datetime import date as dt_date

    dates: list[str] = []
    for d in meta.get("DC.date", []):
        try:
            dt_date.fromisoformat(d)
            dates.append(d)
        except ValueError:
            pass

    filing_date = dates[0] if len(dates) > 0 else None
    grant_date = dates[1] if len(dates) > 1 else None
    # priority_date is typically the earliest DC.date
    priority_date = min(dates) if len(dates) > 1 else None

    # Determine kind_code from publication number suffix
    kind_match = re.search(r"[A-Z]\d+([A-Z]\d?)$", pub_clean)
    kind_code = kind_match.group(1) if kind_match else None

    # Status inference from kind_code
    if kind_code:
        if kind_code.startswith("B"):
            status = "granted"
        elif kind_code.startswith("A"):
            status = "granted" if grant_date else "application"
        elif kind_code in ("U", "Y"):
            status = "utility_model"
        else:
            status = "unknown"
    elif grant_date:
        status = "granted"
    elif filing_date:
        status = "application"
    else:
        status = "unknown"

    # Extract legal events from page timestamps
    events: list[str] = []
    for m in re.finditer(
        r'<time[^>]*datetime="([^"]+)"[^>]*>([^<]+)</time>',
        html,
    ):
        event_text = m.group(2).strip()
        event_date = m.group(1)[:10]
        events.append(f"{event_date}: {event_text}")

    # Assignee from contributors
    contributors = meta.get("DC.contributor", [])
    assignee = (
        contributors[-1] if len(contributors) > 1 else (contributors[0] if contributors else None)
    )

    return {
        "publication_number": publication_number,
        "status": status,
        "kind_code": kind_code,
        "filing_date": filing_date,
        "grant_date": grant_date,
        "priority_date": priority_date,
        "assignee": assignee,
        "events": events[:10],
    }
