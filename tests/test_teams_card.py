"""Tests for the Teams Adaptive Card builder (src/teams/card.py)."""

import pytest

from src.teams.card import (
    build_card,
    build_card_from_markdown,
    is_success,
    normalize_card,
    parse_summary,
    teams_payload,
)

VIEWER = "https://gatlin.example.com"

MD = """# Horizon 每日速递 - 2026-09-02

> 从 54 条内容中筛选出 5 条重要资讯。

## 科技新闻

<a id="item-tech-news-1"></a>
### [谷歌发布 Mantis 框架](https://example.com/mantis) ⭐️ 8.0/10

摘要文本。

### [EMNLP&\\#x27;26 越狱检测](https://example.com/emnlp) ⭐️ 7.0/10

摘要。

## 财经新闻

### [光伏装机量首次超越煤电](https://example.com/solar) ⭐️ 8.0/10

摘要。

## 空分类没有条目

纯文本，没有 ### 条目。
"""


def test_parse_summary_extracts_date_overview_and_sections():
    parsed = parse_summary(MD)
    assert parsed["date"] == "2026-09-02"
    assert parsed["total"] == 54
    assert parsed["picked"] == 5
    assert [s["name"] for s in parsed["sections"]] == ["科技新闻", "财经新闻"]
    assert len(parsed["sections"][0]["items"]) == 2
    assert parsed["sections"][0]["items"][0] == {
        "title": "谷歌发布 Mantis 框架",
        "url": "https://example.com/mantis",
        "score": 8.0,
    }


def test_parse_summary_unescapes_titles():
    parsed = parse_summary(MD)
    titles = [it["title"] for it in parsed["sections"][0]["items"]]
    assert "EMNLP'26 越狱检测" in titles  # \# escape + &#x27; entity cleaned


def test_build_card_structure():
    card = build_card_from_markdown(MD, VIEWER, "zh")
    assert card["type"] == "AdaptiveCard"
    assert card["version"] == "1.4"

    body = card["body"]
    # Title + subtitle + 2 section headers + 3 items + footer
    texts = [e["text"] for e in body if e["type"] == "TextBlock"]
    assert texts[0] == "📰 Horizon 每日速递 · 2026-09-02"
    assert "54" in texts[1] and "5" in texts[1]

    # No Separator / ColumnSet (rejected by the Power Automate connector)
    assert all(e["type"] == "TextBlock" for e in body)

    # One section header per category, in report order
    assert "📰 科技新闻" in texts
    assert "💹 财经新闻" in texts
    assert texts.index("📰 科技新闻") < texts.index("💹 财经新闻")

    # All items rendered as score + linked title
    rows = [t for t in texts if t.startswith("⭐")]
    assert len(rows) == 3
    assert rows[0] == "⭐ 8.0   [谷歌发布 Mantis 框架](https://example.com/mantis)"

    # Footer with per-category counts
    footer = texts[-1]
    assert footer.startswith("📊 包含分类:")
    assert "科技新闻 (2篇)" in footer
    assert "财经新闻 (1篇)" in footer


def test_build_card_button_links_to_viewer_report():
    card = build_card_from_markdown(MD, VIEWER, "zh")
    action = card["actions"][0]
    assert action["type"] == "Action.OpenUrl"
    assert action["url"] == f"{VIEWER}/#/horizon-2026-09-02-zh.md"
    assert "5 篇完整报告" in action["title"]


def test_build_card_normalizes_trailing_slash():
    card = build_card_from_markdown(MD, VIEWER + "/", "zh")
    assert card["actions"][0]["url"] == f"{VIEWER}/#/horizon-2026-09-02-zh.md"


def test_build_card_top_truncates_per_category():
    card = build_card(parse_summary(MD), VIEWER, "zh", top=1)
    rows = [e for e in card["body"] if e["text"].startswith("⭐")]
    assert len(rows) == 2  # one per category
    # footer still counts the full sections
    assert "科技新闻 (2篇)" in card["body"][-1]["text"]


def test_teams_payload_and_normalize_roundtrip():
    card = build_card_from_markdown(MD, VIEWER, "zh")
    payload = teams_payload(card)
    assert payload["type"] == "message"
    assert payload["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert normalize_card(payload) == card
    assert normalize_card(card) is card


def test_normalize_card_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_card({"type": "message", "attachments": []})
    with pytest.raises(ValueError):
        normalize_card({"type": "something-else"})
    with pytest.raises(ValueError):
        normalize_card("not an object")


def test_is_success_accepts_teams_and_power_automate_codes():
    assert is_success(200)
    assert is_success(202)
    assert not is_success(404)
    assert not is_success(500)


# ja summaries use Japanese section names, a Japanese overview line and a
# leading table-of-contents block (numbered list, #anchor links) that must
# NOT be counted as sections/items.
JA_MD = """# Horizon 毎日速報 - 2026-09-03

> 全 81 件のコンテンツから 3 件の重要ニュースを厳選しました。

---

**テクノロジーニュース**
1. [蚂蚁集团 VLDB 最佳论文](#item-tech-news-1) ⭐️ 8.0/10

## テクノロジーニュース

### [蚂蚁集团 VLDB 最佳论文](https://example.com/a) ⭐️ 8.0/10

要旨。

### [米国全域で GPS 誤差](https://example.com/b) ⭐️ 7.0/10

要旨。

## 金融ニュース

### [光伏装机量](https://example.com/c) ⭐️ 8.0/10

要旨。
"""


def test_parse_ja_overview_and_ignores_toc_block():
    parsed = parse_summary(JA_MD)
    assert parsed["date"] == "2026-09-03"
    assert parsed["total"] == 81
    assert parsed["picked"] == 3
    assert [s["name"] for s in parsed["sections"]] == ["テクノロジーニュース", "金融ニュース"]
    assert len(parsed["sections"][0]["items"]) == 2  # TOC line not counted
    assert parsed["sections"][0]["items"][0]["url"] == "https://example.com/a"


def test_build_ja_card_chrome_is_japanese():
    card = build_card_from_markdown(JA_MD, VIEWER, "ja")
    texts = [e["text"] for e in card["body"] if e["type"] == "TextBlock"]

    assert texts[0] == "📰 Horizon 毎日速報 · 2026-09-03"
    assert texts[1] == "本日 81 件のコンテンツから 3 件の重要ニュースを厳選"
    assert "📰 テクノロジーニュース" in texts
    assert "💹 金融ニュース" in texts
    assert texts[-1] == "📊 区分: テクノロジーニュース (2件) · 金融ニュース (1件)"

    action = card["actions"][0]
    assert action["title"] == "👉 今日の 3 件の完全レポートを見る"
    assert action["url"] == f"{VIEWER}/#/horizon-2026-09-03-ja.md"


def test_button_falls_back_to_item_count_without_overview():
    md = "# Horizon 毎日速報 - 2026-09-03\n\n## テクノロジーニュース\n\n### [a](https://example.com/a) ⭐️ 8.0/10\n\n## 金融ニュース\n\n### [b](https://example.com/b) ⭐️ 7.0/10\n"
    card = build_card_from_markdown(md, VIEWER, "ja")
    # no overview line -> picked falls back to the real item count (2)
    assert card["actions"][0]["title"] == "👉 今日の 2 件の完全レポートを見る"
    texts = [e["text"] for e in card["body"]]
    assert "本日 2 件の重要ニュースを厳選" in texts
