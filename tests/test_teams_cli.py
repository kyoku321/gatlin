"""Tests for the horizon --json / --trigger CLI options."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import main as main_module

ROOT = Path(__file__).resolve().parents[1]

MD = """# Horizon 每日速递 - 2026-09-02

> 从 54 条内容中筛选出 2 条重要资讯。

## 科技新闻

### [条目一](https://example.com/a) ⭐️ 8.0/10

摘要。

### [条目二](https://example.com/b) ⭐️ 6.0/10

摘要。
"""


def _valid_config_with_teams(tmp_path: Path, teams: dict) -> None:
    """Write a fully valid config (from config.example.json) plus a teams section."""
    import copy

    base = json.loads((ROOT / "data" / "config.example.json").read_text(encoding="utf-8"))
    merged = copy.deepcopy(base)
    merged["teams"] = teams
    (tmp_path / "config.json").write_text(json.dumps(merged), encoding="utf-8")


def _mute(monkeypatch):
    monkeypatch.setattr(main_module, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(
        main_module,
        "console",
        SimpleNamespace(print=lambda *args, **kwargs: None),
    )


def _write_md(tmp_path, name="horizon-2026-09-02-zh.md"):
    p = tmp_path / name
    p.write_text(MD, encoding="utf-8")
    return p


def test_json_option_writes_card_to_default_path(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--json", str(md), "--viewer-base", "https://v.example.com",
         "--data-dir", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    out = tmp_path / "teams" / "horizon-2026-09-02-zh.json"
    assert out.is_file()
    card = json.loads(out.read_text(encoding="utf-8"))
    assert card["type"] == "AdaptiveCard"
    assert card["actions"][0]["url"] == "https://v.example.com/#/horizon-2026-09-02-zh.md"


def test_json_option_missing_viewer_base_fails(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    monkeypatch.setattr(
        "sys.argv", ["horizon", "--json", str(md), "--data-dir", str(tmp_path)]
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 2


def test_json_option_uses_viewer_base_from_config(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    _valid_config_with_teams(tmp_path, {"viewer_base_url": "https://cfg.example.com"})
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--json", str(md), "--data-dir", str(tmp_path)],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    card = json.loads((tmp_path / "teams" / "horizon-2026-09-02-zh.json").read_text())
    assert card["actions"][0]["url"] == "https://cfg.example.com/#/horizon-2026-09-02-zh.md"


def test_json_option_requires_lang_when_name_does_not_match(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = tmp_path / "notes.md"
    md.write_text(MD, encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--json", str(md), "--viewer-base", "https://v.example.com"],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 2


def test_trigger_skips_without_webhook(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    monkeypatch.delenv("HORIZON_TEAMS_WEBHOOK_URL", raising=False)

    calls = []

    def fail_if_called(*a, **k):
        calls.append(a)
        raise AssertionError("post_card must not be called")

    monkeypatch.setattr(main_module, "post_card", fail_if_called)

    # Build the card first, then trigger it without a webhook URL.
    argv = [
        "horizon",
        "--json", str(md), "--viewer-base", "https://v.example.com",
        "--trigger", str(tmp_path / "teams" / "horizon-2026-09-02-zh.json"),
        "--data-dir", str(tmp_path),
    ]
    monkeypatch.setattr("sys.argv", argv)

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert calls == []


def test_trigger_posts_card_to_explicit_webhook(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    sent = []

    def fake_post(card, url, timeout=30.0):
        sent.append((card, url))
        return SimpleNamespace(status_code=202, text="")

    monkeypatch.setattr(main_module, "post_card", fake_post)
    monkeypatch.setattr(
        "sys.argv",
        [
            "horizon",
            "--json", str(md), "--viewer-base", "https://v.example.com",
            "--trigger", str(tmp_path / "teams" / "horizon-2026-09-02-zh.json"),
            "https://webhook.example.com/invoke",
            "--data-dir", str(tmp_path),
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    card, url = sent[0]
    assert url == "https://webhook.example.com/invoke"
    assert card["type"] == "AdaptiveCard"


def test_trigger_uses_webhook_env_option(monkeypatch, tmp_path):
    _mute(monkeypatch)
    sent = []

    def fake_post(card, url, timeout=30.0):
        sent.append((card, url))
        return SimpleNamespace(status_code=202, text="")

    monkeypatch.setattr(main_module, "post_card", fake_post)
    monkeypatch.setenv("HORIZON_TEAMS_WEBHOOK_URL_JA", "https://ja-webhook.example.com/x")
    monkeypatch.delenv("HORIZON_TEAMS_WEBHOOK_URL", raising=False)
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps({"type": "AdaptiveCard", "body": []}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--trigger", str(card_path),
         "--webhook-env", "HORIZON_TEAMS_WEBHOOK_URL_JA"],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert sent[0][1] == "https://ja-webhook.example.com/x"


def test_trigger_explicit_url_wins_over_webhook_env(monkeypatch, tmp_path):
    _mute(monkeypatch)
    sent = []

    def fake_post(card, url, timeout=30.0):
        sent.append((card, url))
        return SimpleNamespace(status_code=200, text="")

    monkeypatch.setattr(main_module, "post_card", fake_post)
    monkeypatch.setenv("HORIZON_TEAMS_WEBHOOK_URL_JA", "https://env.example.com/x")
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps({"type": "AdaptiveCard", "body": []}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "horizon", "--trigger", str(card_path), "https://explicit.example.com/x",
            "--webhook-env", "HORIZON_TEAMS_WEBHOOK_URL_JA",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 0
    assert sent[0][1] == "https://explicit.example.com/x"


def test_trigger_http_failure_exits_nonzero(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    monkeypatch.setattr(
        main_module,
        "post_card",
        lambda card, url, timeout=30.0: SimpleNamespace(status_code=500, text="boom"),
    )
    card_path = tmp_path / "card.json"
    card_path.write_text(json.dumps({"type": "AdaptiveCard", "body": []}), encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--trigger", str(card_path), "https://webhook.example.com/x"],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 1


def test_json_and_date_are_mutually_exclusive(monkeypatch, tmp_path):
    _mute(monkeypatch)
    md = _write_md(tmp_path)
    monkeypatch.setattr(
        "sys.argv",
        ["horizon", "--json", str(md), "--date", "2026-09-02"],
    )

    with pytest.raises(SystemExit) as exc:
        main_module.main()

    assert exc.value.code == 1
