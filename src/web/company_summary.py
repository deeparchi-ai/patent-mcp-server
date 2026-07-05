"""Company patent summary — zero-cost assignee overview via Google Patents + Playwright.

Uses headless Chromium to render the Google Patents assignee search page,
extracting structured summary: total patents, jurisdictions, top technology areas,
activity level, and risk assessment.

This is the ONLY tool that scrapes the assignee-level page (all other web tools
target individual patent pages). Direct HTTP requests are blocked by Google's
CAPTCHA; Playwright with stealth headers is required.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

GOOGLE_PATENTS_ASSIGNEE_URL = "https://patents.google.com/?assignee={name}"

# Technology keywords for area extraction (filtered: no generic method/device/system)
TECH_KEYWORDS = [
    "battery", "charging", "power", "inverter", "solar", "photovoltaic",
    "energy", "motor", "sensor", "wireless", "communication",
    "display", "audio", "camera", "algorithm", "learning", "network",
    "cooling", "heating", "robot", "cleaner", "navigation",
    "bms", "equalization", "obstacle", "map", "parallel",
    "brake", "autonomous", "lidar", "radar", "driving",
    "vehicle", "engine", "transmission", "suspension",
    "semiconductor", "chip", "memory", "processor",
    "pharmaceutical", "antibody", "protein", "gene",
    "blockchain", "encryption", "token", "ledger",
]


def _parse_company_summary(html: str, company_name: str) -> dict[str, Any]:
    """Parse Google Patents assignee search page HTML into structured summary."""

    summary: dict[str, Any] = {
        "company_name": company_name,
        "total_patents": 0,
        "top_areas": [],
        "recent_patents": [],
        "jurisdictions": [],
        "activity_level": "unknown",
        "risk_label": "unknown",
        "risk_reason": "",
    }

    # ── Total patent count ──
    count_match = re.search(r"About\s+([\d,]+)\s+results", html)
    if count_match:
        summary["total_patents"] = int(count_match.group(1).replace(",", ""))

    # ── Parse articles: each has h3(title) + two h4(meta, dates) ──
    articles_raw = re.findall(r"<article[^>]*>(.*?)</article>", html, re.DOTALL)
    for art in articles_raw:
        title_match = re.search(r"<h3[^>]*>(.*?)</h3>", art, re.DOTALL)
        if not title_match:
            continue
        title = re.sub(r"<[^>]+>", "", title_match.group(1)).strip()

        h4_matches = re.findall(r"<h4[^>]*>(.*?)</h4>", art, re.DOTALL)
        meta_text = ""
        date_text = ""

        for h4 in h4_matches:
            clean = re.sub(r"<[^>]+>", " ", h4)
            clean = re.sub(r"\s+", " ", clean).strip()
            if "Priority" in clean or "Filed" in clean:
                date_text = clean
            else:
                meta_text = meta_text or clean  # keep first non-date h4

        # Extract jurisdictions (uppercase letter pairs at start)
        jd_parts: list[str] = []
        for part in meta_text.split():
            if re.match(r"^[A-Z]{2}$", part):
                jd_parts.append(part)
            else:
                break
        jurisdictions_str = " ".join(jd_parts)

        # Extract patent number
        pn_match = re.search(r"([A-Z]{2,3}\d+[A-Z]?\d*)", meta_text)
        patent_no = pn_match.group(0) if pn_match else ""

        # Extract year from date_text
        year = 0
        year_matches = re.findall(
            r"(?:Priority|Filed|Granted|Published)\s+(\d{4})", date_text
        )
        if year_matches:
            years = [int(y) for y in year_matches]
            year = min(years) if years else 0

        summary["recent_patents"].append({
            "title": title[:120],
            "patent_no": patent_no,
            "jurisdictions": jurisdictions_str,
            "year": year,
        })

    # ── Jurisdiction coverage ──
    all_jds: set[str] = set()
    for p in summary["recent_patents"]:
        for j in p["jurisdictions"].split():
            if len(j) == 2 and j.isalpha():
                all_jds.add(j)
    summary["jurisdictions"] = sorted(all_jds)

    # ── Top technology areas ──
    title_words: list[str] = []
    for p in summary["recent_patents"]:
        title_words.extend(p["title"].lower().split())

    area_counts: dict[str, int] = {}
    for kw in TECH_KEYWORDS:
        count = sum(1 for w in title_words if kw in w)
        if count >= 2:
            area_counts[kw] = count

    summary["top_areas"] = sorted(
        area_counts, key=lambda k: area_counts[k], reverse=True
    )[:5]

    # ── Activity level ──
    recent_years = [p["year"] for p in summary["recent_patents"] if p["year"] >= 2023]
    if len(recent_years) >= 5:
        summary["activity_level"] = "active"
    elif len(recent_years) >= 2:
        summary["activity_level"] = "moderate"
    elif summary["total_patents"] > 0:
        summary["activity_level"] = "dormant"
    else:
        summary["activity_level"] = "none"

    # ── Risk assessment ──
    total = summary["total_patents"]
    jd_count = len(summary["jurisdictions"])
    if total == 0:
        summary["risk_label"] = "🟢 low"
        summary["risk_reason"] = (
            "未发现专利记录，海外IP风险较低（建议确认公司名准确性或尝试英文名）"
        )
    elif total < 100:
        summary["risk_label"] = "🟢 low"
        summary["risk_reason"] = f"仅{total}项专利，技术壁垒低"
    elif total < 1000:
        if jd_count >= 3:
            summary["risk_label"] = "🟡 medium"
            summary["risk_reason"] = (
                f"{total}项专利覆盖{jd_count}国，有一定技术壁垒"
            )
        else:
            summary["risk_label"] = "🟢 low"
            summary["risk_reason"] = f"{total}项专利，海外布局有限"
    else:
        if jd_count >= 5:
            summary["risk_label"] = "🔴 high"
            summary["risk_reason"] = (
                f"{total}项专利覆盖{jd_count}国，技术壁垒较高"
            )
        else:
            summary["risk_label"] = "🟡 medium"
            summary["risk_reason"] = f"{total}项专利，需关注具体技术领域"

    return summary


async def get_company_summary(company_name: str) -> dict[str, Any]:
    """Scrape Google Patents assignee page and return structured company summary.

    Uses Playwright with headless Chromium to bypass Google's CAPTCHA.
    Typical latency: 5-10 seconds (browser launch + page render).

    Args:
        company_name: Company name in Chinese or English (e.g. "正浩创新", "Anker")

    Returns:
        Dict with: company_name, total_patents, top_areas, recent_patents,
        jurisdictions, activity_level, risk_label, risk_reason
    """
    from playwright.async_api import async_playwright  # type: ignore[import-untyped]

    encoded = company_name.replace(" ", "+")
    url = GOOGLE_PATENTS_ASSIGNEE_URL.format(name=encoded)

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")

            # Wait for results
            try:
                await page.wait_for_selector("article", timeout=10000)
            except Exception:
                logger.info("No article elements found for %s", company_name)

            html = await page.content()
            await browser.close()

        return _parse_company_summary(html, company_name)

    except Exception as e:
        logger.error("Company summary failed for %s: %s", company_name, e)
        return {
            "company_name": company_name,
            "total_patents": 0,
            "error": str(e),
            "risk_label": "unknown",
            "risk_reason": f"查询失败: {e}",
        }
