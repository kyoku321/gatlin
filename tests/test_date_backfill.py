"""Tests for the horizon --date backfill mode."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from src import main as main_module
from src.models import ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator


# ── Orchestrator date window helpers ──


def test_date_window_utc_boundaries():
    since, until = HorizonOrchestrator._date_window("2026-09-01")
    assert since == datetime(2026, 9, 1, 0, 0, tzinfo=timezone.utc)
    assert until == datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
    assert until == since + timedelta(days=1)


def test_date_window_month_boundary():
    since, until = HorizonOrchestrator._date_window("2026-09-30")
    assert until == datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)


def _item(minutes):
    base = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    return ContentItem(
        id=f"rss:t:{minutes}",
        source_type=SourceType.RSS,
        title=f"item {minutes}",
        url=f"https://example.com/{minutes}",
        published_at=base + timedelta(minutes=minutes),
    )


def test_filter_date_window_keeps_only_items_before_until():
    until = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
    items = [
        _item(-1),          # 11:59 -> keep (same day)
        _item(60 * 12),     # 00:00 next day -> drop (until is exclusive)
        _item(60 * 24),     # next day -> drop
    ]
    kept, dropped = HorizonOrchestrator._filter_date_window(items, until)
    assert [item.id for item in kept] == ["rss:t:-1"]
    assert dropped == 2


def test_filter_date_window_all_outside():
    until = datetime(2026, 9, 2, 0, 0, tzinfo=timezone.utc)
    kept, dropped = HorizonOrchestrator._filter_date_window([_item(60 * 25)], until)
    assert kept == []
    assert dropped == 1


# ── CLI ──


class _FailStorage:
    def __init__(self, data_dir, config_path):
        pass

    def load_config(self):
        raise FileNotFoundError


class _OKStorage:
    def __init__(self, data_dir, config_path):
        pass

    def load_config(self):
        return SimpleNamespace(display=SimpleNamespace(icon_style="emoji"))


def _run_cli(monkeypatch, argv, storage_class=None):
    """Run main() with given argv; returns (exit_code, rendered, run_kwargs)."""
    output = []
    run_kwargs = {}

    class FakeConsole:
        def print(self, *args, **kwargs):
            output.append(" ".join(map(str, args)))

        def print_exception(self, *args, **kwargs):
            output.append("<exception-traceback>")

    def factory(config, storage, console=None):
        class FakeOrchestrator:
            async def run(self, **kwargs):
                run_kwargs.update(kwargs)

        return FakeOrchestrator()

    monkeypatch.setattr(main_module, "StorageManager", storage_class or _FailStorage)
    monkeypatch.setattr(main_module, "configure_logging", lambda console, level=None: None)
    monkeypatch.setattr(main_module, "console", FakeConsole())
    monkeypatch.setattr(main_module, "HorizonOrchestrator", factory)
    monkeypatch.setattr("sys.argv", ["horizon", *argv])
    exit_code = 0
    try:
        main_module.main()
    except SystemExit as exc:
        exit_code = exc.code or 0
    except Exception as exc:  # pragma: no cover - surface real failures
        raise AssertionError(f"main() raised: {exc!r}\noutput:\n{chr(10).join(output)}") from exc
    return exit_code, "\n".join(output), run_kwargs


def test_cli_date_and_hours_are_mutually_exclusive(monkeypatch):
    code, rendered, _ = _run_cli(monkeypatch, ["--date", "2026-09-01", "--hours", "2"])
    assert code == 1
    assert "mutually exclusive" in rendered


def test_cli_invalid_date_rejected(monkeypatch):
    code, rendered, _ = _run_cli(monkeypatch, ["--date", "2026/09/01"])
    assert code == 1
    assert "Invalid --date" in rendered


def test_cli_date_forwards_backfill_window_and_skips_notify(monkeypatch):
    code, _, run_kwargs = _run_cli(monkeypatch, ["--date", "2026-09-01"], _OKStorage)
    assert code == 0
    assert run_kwargs == {"force_hours": None, "date": "2026-09-01", "notify": False}


def test_cli_date_with_notify_forces_webhook(monkeypatch):
    code, _, run_kwargs = _run_cli(monkeypatch, ["--date", "2026-09-01", "--notify"], _OKStorage)
    assert code == 0
    assert run_kwargs["notify"] is True
    assert run_kwargs["date"] == "2026-09-01"


def test_cli_default_run_keeps_notify_enabled(monkeypatch):
    code, _, run_kwargs = _run_cli(monkeypatch, [], _OKStorage)
    assert code == 0
    assert run_kwargs == {"force_hours": None, "date": None, "notify": True}


def test_cli_hours_still_forwarded(monkeypatch):
    code, _, run_kwargs = _run_cli(monkeypatch, ["--hours", "6"], _OKStorage)
    assert code == 0
    assert run_kwargs == {"force_hours": 6, "date": None, "notify": True}
