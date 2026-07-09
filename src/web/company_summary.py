"""Company patent summary — zero-cost assignee overview via Google Patents + Playwright.

Uses headless Chromium to render the Google Patents assignee search page TWICE:
1. Default sort (relevance) → total count + jurisdiction coverage
2. Sorted by newest → recent activity + tech trend detection

Direct HTTP requests are blocked by Google's CAPTCHA; Playwright required.
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

GOOGLE_PATENTS_URL = "https://patents.google.com/"

# Bigram-level tech phrase extraction (combines 2+ adjacent tech words)
TECH_BIGRAMS = {
    "artificial intelligence": [
        "machine learning",
        "deep learning",
        "neural network",
        "natural language",
        "computer vision",
        "reinforcement learning",
    ],
    "power & energy": [
        "power source",
        "power supply",
        "energy storage",
        "power conversion",
        "battery management",
        "charging station",
        "solar cell",
        "fuel cell",
        "wireless charging",
        "power control",
    ],
    "autonomous & robotics": [
        "autonomous driving",
        "autonomous vehicle",
        "self driving",
        "unmanned aerial",
        "mobile robot",
        "path planning",
        "obstacle detection",
    ],
    "semiconductor & hardware": [
        "integrated circuit",
        "semiconductor device",
        "printed circuit",
        "memory device",
        "display panel",
        "light emitting",
    ],
    "communication & network": [
        "wireless communication",
        "data transmission",
        "network device",
        "signal processing",
        "antenna array",
        "beam forming",
    ],
    "biotech & pharma": [
        "monoclonal antibody",
        "nucleic acid",
        "amino acid",
        "pharmaceutical composition",
        "cell therapy",
        "gene therapy",
    ],
}

# Single-word tech signals (filtered: no generic apparatus/method/device/system)
TECH_SIGNALS = [
    "battery",
    "charging",
    "inverter",
    "solar",
    "photovoltaic",
    "motor",
    "sensor",
    "lidar",
    "radar",
    "brake",
    "driving",
    "engine",
    "transmission",
    "camera",
    "gimbal",
    "drone",
    "uav",
    "propeller",
    "semiconductor",
    "chip",
    "processor",
    "memory",
    "transistor",
    "blockchain",
    "encryption",
    "token",
    "ledger",
    "cryptographic",
    "antibody",
    "protein",
    "gene",
    "cell",
    "pharmaceutical",
]

FRIENDLY_LABELS: dict[str, str] = {
    "battery": "电池/储能",
    "charging": "充电技术",
    "inverter": "逆变器",
    "solar": "太阳能",
    "photovoltaic": "光伏",
    "motor": "电机",
    "sensor": "传感器",
    "lidar": "激光雷达",
    "radar": "雷达",
    "driving": "自动驾驶",
    "camera": "影像/相机",
    "gimbal": "云台",
    "drone": "无人机",
    "uav": "无人机",
    "semiconductor": "半导体",
    "chip": "芯片",
    "processor": "处理器",
    "memory": "存储",
    "blockchain": "区块链",
    "encryption": "加密",
    "antibody": "抗体",
    "protein": "蛋白质",
    "gene": "基因",
    "cell": "细胞治疗",
}


def _parse_patent_list(html: str) -> list[dict[str, Any]]:
    """Parse patent article elements from Google Patents HTML."""
    patents: list[dict[str, Any]] = []
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
                meta_text = meta_text or clean

        # Jurisdictions
        jd_parts: list[str] = []
        for part in meta_text.split():
            if re.match(r"^[A-Z]{2}$", part):
                jd_parts.append(part)
            else:
                break

        # Patent number
        pn_match = re.search(r"([A-Z]{2,3}\d+[A-Z]?\d*)", meta_text)
        patent_no = pn_match.group(0) if pn_match else ""

        # Year — use LATEST of Priority/Filed/Granted/Published (not earliest)
        year = 0
        year_matches = re.findall(r"(?:Priority|Filed|Granted|Published)\s+(\d{4})", date_text)
        if year_matches:
            years = [int(y) for y in year_matches]
            year = max(years)  # Latest date = most recent activity indicator

        patents.append(
            {
                "title": title[:120],
                "patent_no": patent_no,
                "jurisdictions": " ".join(jd_parts),
                "year": year,
            }
        )

    return patents


def _extract_tech_areas(all_titles: list[str]) -> list[str]:
    """Extract technology areas from patent titles using bigrams + signals."""
    text = " ".join(all_titles).lower()
    scores: dict[str, int] = {}

    # Check bigram patterns first (more precise)
    for _category, phrases in TECH_BIGRAMS.items():
        for phrase in phrases:
            count = text.count(phrase)
            if count >= 2:
                scores[phrase] = count

    # Then single-word signals as fallback
    for kw in TECH_SIGNALS:
        count = sum(1 for t in all_titles if kw in t.lower())
        if count >= 2 and not any(kw in k for k in scores):
            scores[kw] = count

    # Sort by score, map to friendly labels
    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)[:5]
    return [FRIENDLY_LABELS.get(r, r) for r in ranked]


def _assess_activity(patents: list[dict[str, Any]], total: int) -> tuple[str, str]:
    """Assess activity level from patent recency.

    Uses BOTH default-sorted sample and total count to estimate.
    """
    years = [p["year"] for p in patents if p["year"] > 0]
    if not years:
        return ("none", "无活跃专利记录")

    latest = max(years)
    recent = [y for y in years if y >= 2023]
    very_recent = [y for y in years if y >= 2024]

    if very_recent and len(very_recent) >= 3:
        return ("active", f"近两年持续申请（最新{latest}年），研发活跃")
    elif recent and len(recent) >= 2:
        return ("active", f"有{len(recent)}项{min(recent)}年后专利，技术仍在迭代")
    elif latest >= 2022:
        if total > 1000:
            return ("moderate", f"最新专利{latest}年，大量存量专利但近期申请减少")
        else:
            return ("moderate", f"最新专利{latest}年")
    elif total > 0:
        return ("dormant", f"最新专利{latest}年，近年未见新申请")
    else:
        return ("none", "未发现专利")


def _assess_risk(total: int, jd_count: int, activity: str, has_overseas: bool) -> tuple[str, str]:
    """Multi-dimensional risk assessment."""
    if total == 0:
        return ("🟢 low", "未发现专利记录（建议确认公司名或尝试英文名）")

    # Base risk from volume
    if total < 100:
        base = "low"
    elif total < 1000:
        base = "medium"
    else:
        base = "high"

    # Jurisdiction multiplier
    if jd_count >= 5 and has_overseas:
        if base == "high":
            return ("🔴 high", f"{total:,}项专利覆盖{jd_count}国，全球布局，技术壁垒高")
        elif base == "medium":
            return ("🟡 medium", f"{total:,}项专利覆盖{jd_count}国，海外有布局")

    if base == "high":
        if jd_count >= 3:
            return ("🔴 high", f"{total:,}项专利覆盖{jd_count}国，技术壁垒较高")
        return ("🟡 medium", f"{total:,}项专利，海外布局有限")

    if base == "medium":
        if jd_count >= 3:
            return ("🟡 medium", f"{total:,}项专利覆盖{jd_count}国，有一定壁垒")
        return ("🟢 low", f"{total:,}项专利，海外布局少")

    return ("🟢 low", f"仅{total}项专利，技术壁垒低")


def _parse_company_summary(
    default_html: str, newest_html: str, company_name: str
) -> dict[str, Any]:
    """Parse TWO Google Patents pages (default + newest) into summary."""

    # ── Total patent count (from default page) ──
    count_match = re.search(r"About\s+([\d,]+)\s+results", default_html)
    total = int(count_match.group(1).replace(",", "")) if count_match else 0

    # ── Parse both pages ──
    default_patents = _parse_patent_list(default_html)
    newest_patents = _parse_patent_list(newest_html)

    # Combine for jurisdiction analysis (from default page, which has more variety)
    all_patents_for_jd = default_patents + newest_patents

    # Jurisdiction coverage
    all_jds: set[str] = set()
    for p in all_patents_for_jd:
        for j in p["jurisdictions"].split():
            if len(j) == 2 and j.isalpha():
                all_jds.add(j)
    jurisdictions = sorted(all_jds)
    has_overseas = bool(all_jds - {"CN"})

    # ── Activity level (from newest-sorted page) ──
    activity_level, activity_note = _assess_activity(newest_patents, total)

    # ── Tech areas (combine both pages for broader sample) ──
    all_titles = [p["title"] for p in default_patents + newest_patents]
    top_areas = _extract_tech_areas(all_titles)

    # ── Risk ──
    risk_label, risk_reason = _assess_risk(total, len(jurisdictions), activity_level, has_overseas)

    # ── Recent patents (from newest page, top 5) ──
    recent = sorted(newest_patents, key=lambda p: p["year"], reverse=True)[:5]

    return {
        "company_name": company_name,
        "total_patents": total,
        "top_areas": top_areas,
        "recent_patents": recent,
        "jurisdictions": jurisdictions,
        "activity_level": activity_level,
        "activity_note": activity_note,
        "risk_label": risk_label,
        "risk_reason": risk_reason,
    }


async def get_company_summary(company_name: str) -> dict[str, Any]:
    """Scrape Google Patents for a company's patent portfolio summary.

    Loads the default assignee search page and extracts structured summary.
    Uses the LATEST date (Priority/Filed/Granted/Published) for each patent
    to assess recent activity — Google's default relevance sort already surfaces
    well-cited patents, which often include recently granted ones.

    Typical latency: 5-10 seconds.
    """
    from playwright.async_api import async_playwright

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            encoded = company_name.replace(" ", "+")
            url = f"{GOOGLE_PATENTS_URL}?assignee={encoded}"
            await page.goto(url, timeout=20000, wait_until="domcontentloaded")
            with contextlib.suppress(Exception):
                await page.wait_for_selector("article", timeout=10000)

            html = await page.content()
            await browser.close()

        # Use same HTML for both — activity detection uses latest dates
        return _parse_company_summary(html, html, company_name)

    except Exception as e:
        logger.error("Company summary failed for %s: %s", company_name, e)
        return {
            "company_name": company_name,
            "total_patents": 0,
            "error": str(e),
            "risk_label": "unknown",
            "risk_reason": f"查询失败: {e}",
        }
