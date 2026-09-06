"""Build and send Teams Adaptive Cards from Horizon daily summary markdown.

The card layout is driven by the generated summary file
(``data/summaries/horizon-YYYY-MM-DD-<lang>.md``): one section per
category with every item (score + linked title), a per-category count
footer, and a button linking back to the viewer site.

Connector constraints (learned live against the Power Automate Teams
connector, action "Post card in a chat or channel"):

* The trigger body must be the *bare* Adaptive Card JSON
  (``"type": "AdaptiveCard"``) — the Teams activity wrapper
  (``{"type": "message", ...}``) fails with "Property 'type' must be
  'AdaptiveCard'".
* ``ColumnSet`` and ``Separator`` are rejected with "Payload is
  incorrect: unsupported card element" — use plain TextBlocks with
  spacing instead.
"""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

# ## 科技新闻
SECTION_RE = re.compile(r"^## +(.+?)\s*$", re.MULTILINE)
# ### [Title](https://source) ⭐️ 8.0/10
ITEM_RE = re.compile(
    r"^### +\[(?P<title>.+?)\]\((?P<url>\S+?)\)\s*⭐️?\s*(?P<score>\d+(?:\.\d+)?)\s*/10",
    re.MULTILINE,
)
# > 从 54 条内容中筛选出 23 条重要资讯。
OVERVIEW_RE = re.compile(r"^> +从\s*(\d+)\s*条.+?筛选出\s*(\d+)\s*条", re.MULTILINE)
# > 全 81 件のコンテンツから 44 件の重要ニュースを厳選しました。
OVERVIEW_RE_JA = re.compile(r"^> +.*?(\d+)\s*件.*?(\d+)\s*件", re.MULTILINE)
# # Horizon 每日速递 - 2026-09-02
DATE_RE = re.compile(r"^# +.+?\s*-\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)

LANG_TITLES = {
    "zh": "每日速递",
    "ja": "毎日速報",
    "en": "Daily",
}

CATEGORY_ICONS = {
    "科技新闻": "📰",
    "科技博客": "✍️",
    "财经新闻": "💹",
    "AI 创作者雷达": "🎨",
    "テクノロジーニュース": "📰",
    "テクノロジーブログ": "✍️",
    "金融ニュース": "💹",
    "AI クリエイター・レーダー": "🎨",
}

# Card chrome (subtitle / footer / button) per language. ``{counts}`` is the
# joined "Category (N<unit>)" list; the unit keeps the counter native.
CARD_TEXTS = {
    "zh": {
        "subtitle": "今日从 {total} 条源数据中精选出 {picked} 条重要资讯",
        "subtitle_no_total": "今日精选出 {picked} 条重要资讯",
        "footer": "📊 包含分类: {counts}",
        "count_unit": "篇",
        "button": "👉 点击查看今日 {picked} 篇完整报告",
    },
    "ja": {
        "subtitle": "本日 {total} 件のコンテンツから {picked} 件の重要ニュースを厳選",
        "subtitle_no_total": "本日 {picked} 件の重要ニュースを厳選",
        "footer": "📊 区分: {counts}",
        "count_unit": "件",
        "button": "👉 今日の {picked} 件の完全レポートを見る",
    },
    "en": {
        "subtitle": "{picked} important stories picked from {total} sources today",
        "subtitle_no_total": "{picked} important stories picked today",
        "footer": "📊 Categories: {counts}",
        "count_unit": "",
        "button": "👉 View today's full report ({picked} items)",
    },
}

DEFAULT_WEBHOOK_ENV = "HORIZON_TEAMS_WEBHOOK_URL"


def parse_summary(md: str) -> dict:
    """Parse a generated summary markdown into date/overview/sections."""
    date_m = DATE_RE.search(md)
    date = date_m.group(1) if date_m else ""

    total = picked = None
    ov = OVERVIEW_RE.search(md) or OVERVIEW_RE_JA.search(md)
    if ov:
        total, picked = int(ov.group(1)), int(ov.group(2))

    # Split into ## sections, keep order
    sections: list[dict] = []
    matches = list(SECTION_RE.finditer(md))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(md)
        body = md[start:end]
        items = [
            {
                # Unescape markdown backslash-escapes (\# etc.) and HTML
                # entities (&#x27;) so the card text renders cleanly.
                "title": html.unescape(im.group("title").replace("\\", "")).strip(),
                "url": im.group("url").strip(),
                "score": float(im.group("score")),
            }
            for im in ITEM_RE.finditer(body)
        ]
        if items:
            sections.append({"name": m.group(1).strip(), "items": items})

    return {"date": date, "total": total, "picked": picked, "sections": sections}


def _item_row(score: float, title: str, url: str) -> dict:
    """One card row: star + score + linked title.

    NOTE: keep this a single TextBlock — ColumnSet is rejected by the
    Power Automate Teams connector (see module docstring).
    """
    return {
        "type": "TextBlock",
        "text": f"⭐ {score:.1f}   [{title}]({url})",
        "size": "Medium",
        "wrap": True,
        "spacing": "Small",
    }


def _section_header(text: str, first: bool = False) -> dict:
    # NOTE: no Separator element — spacing provides the visual break.
    return {
        "type": "TextBlock",
        "text": text,
        "size": "Medium",
        "weight": "Bolder",
        "spacing": "None" if first else "Extra",
    }


def build_card(
    parsed: dict, viewer_base: str, lang: str, top: int = 0
) -> dict:
    """Build the bare Adaptive Card dict for a parsed summary.

    ``top`` caps items per category (0 = all, the default).
    """
    date = parsed["date"]
    sections = parsed["sections"]
    total = parsed.get("total")
    texts = CARD_TEXTS.get(lang) or CARD_TEXTS["en"]
    # picked can be None when the overview line didn't parse (e.g. new
    # language); fall back to the real item count so the button/subtitle
    # always show a number.
    picked = parsed.get("picked") or sum(len(s["items"]) for s in sections)
    title_base = LANG_TITLES.get(lang, "Daily")

    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": f"📰 {title_base} · {date}",
            "size": "Large",
            "weight": "Bolder",
        }
    ]
    if total is not None:
        subtitle = texts["subtitle"].format(total=total, picked=picked)
    else:
        subtitle = texts["subtitle_no_total"].format(picked=picked)
    body.append(
        {
            "type": "TextBlock",
            "text": subtitle,
            "isSubtle": True,
            "size": "Small",
            "spacing": "Small",
        }
    )

    # One section per category, in report order, all items (top>0 truncates).
    for i, s in enumerate(sections):
        icon = CATEGORY_ICONS.get(s["name"], "📌")
        body.append(_section_header(f"{icon} {s['name']}", first=(i == 0)))
        items = s["items"][:top] if top > 0 else s["items"]
        for it in items:
            body.append(_item_row(it["score"], it["title"], it["url"]))

    # Footer: per-category counts (native counter unit per language)
    unit = texts["count_unit"]
    counts = " · ".join(
        f"{s['name']} ({len(s['items'])}{unit})" for s in sections
    )
    if counts:
        body.append(
            {
                "type": "TextBlock",
                "text": texts["footer"].format(counts=counts),
                "isSubtle": True,
                "size": "Small",
                "spacing": "Extra",
            }
        )

    report_url = f"{viewer_base.rstrip('/')}/#/horizon-{date}-{lang}.md"
    button_text = texts["button"].format(picked=picked)

    return {
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "type": "AdaptiveCard",
        "version": "1.4",
        "body": body,
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": button_text,
                "url": report_url,
            }
        ],
    }


def build_card_from_markdown(
    md: str, viewer_base: str, lang: str, top: int = 0
) -> dict:
    """Parse ``md`` and build the card in one step."""
    return build_card(parse_summary(md), viewer_base, lang, top=top)


def teams_payload(card: dict) -> dict:
    """Wrap a bare card in the Teams activity payload.

    Only useful for real Teams *incoming webhooks*; Power Automate
    flows that pass the trigger body straight to a post-card action
    expect the bare card (see module docstring).
    """
    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": card,
            }
        ],
    }


def normalize_card(payload: Any) -> dict:
    """Accept either a bare card or a Teams activity payload; return the card."""
    if not isinstance(payload, dict):
        raise ValueError("card JSON must be an object")
    if payload.get("type") == "message":
        attachments = payload.get("attachments") or []
        if not attachments:
            raise ValueError("activity payload has no attachments")
        card = attachments[0].get("content")
        if not isinstance(card, dict):
            raise ValueError("attachment content is not an object")
        return card
    if payload.get("type") != "AdaptiveCard":
        raise ValueError(f"expected an AdaptiveCard, got type {payload.get('type')!r}")
    return payload


def post_card(card: dict, webhook_url: str, timeout: float = 30.0) -> httpx.Response:
    """POST the bare card to a webhook. Returns the httpx response."""
    return httpx.post(webhook_url, json=card, timeout=timeout)


def is_success(status_code: int) -> bool:
    """200 (Teams incoming webhook) or 202 (Power Automate trigger)."""
    return status_code in (200, 202)
