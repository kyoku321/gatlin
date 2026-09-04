"""CLI entry point for Horizon."""

import argparse
import asyncio
import json
import os
import re
import shlex
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from ._cli import add_data_dir_arguments, add_log_level_argument
from .console_icons import get_icons
from .logging_config import configure_logging
from .storage.manager import ConfigError, StorageManager
from .orchestrator import HorizonOrchestrator
from .teams.card import (
    DEFAULT_WEBHOOK_ENV,
    build_card,
    is_success,
    normalize_card,
    parse_summary,
    post_card,
)


console = Console(stderr=True)


def print_banner():
    """Print the application banner."""
    banner = r"""
[bold blue]
  _    _            _
 | |  | |          (_)
 | |__| | ___  _ __ _ ___  ___  _ __
 |  __  |/ _ \| '__| |_  / / _ \| '_ \
 | |  | | (_) | |  | |/ / | (_) | | | |
 |_|  |_|\___/|_|  |_/___| \___/|_| |_|
[/bold blue]
[cyan]  AI-Driven Information Aggregation System[/cyan]
    """
    console.print(banner)


def main():
    """Main CLI entry point."""
    configure_logging(console)
    print_banner()
    icons = get_icons()

    parser = argparse.ArgumentParser(description="Horizon - AI-Driven Information Aggregation System")
    parser.add_argument("--hours", type=int, help="Force fetch from last N hours")
    parser.add_argument(
        "--date",
        type=str,
        metavar="YYYY-MM-DD",
        help=(
            "Backfill: fetch only content published on this UTC date and "
            "write the daily report for that date (webhook is skipped "
            "unless --notify is given)"
        ),
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="Send webhook notifications in --date backfill mode",
    )
    parser.add_argument(
        "--json",
        dest="json_md",
        metavar="MARKDOWN_PATH",
        help=(
            "Convert a daily summary markdown file into a Teams Adaptive Card "
            "JSON file and exit (no pipeline run). Default output: "
            "<data-dir>/teams/<name>.json"
        ),
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Output path for --json (default: <data-dir>/teams/<name>.json)",
    )
    parser.add_argument(
        "--viewer-base",
        metavar="URL",
        help="Viewer base URL for report links (default: teams.viewer_base_url from config)",
    )
    parser.add_argument(
        "--lang",
        metavar="LANG",
        help="Language code for --json (default: inferred from the file name)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=0,
        metavar="N",
        help="Max items per category for --json (default: all)",
    )
    parser.add_argument(
        "--trigger",
        nargs="+",
        metavar="VALUE",
        help=(
            "POST a Teams Adaptive Card JSON file to a webhook and exit: "
            "<card_json> [webhook_url]. The webhook URL defaults to the env "
            f"var named by teams.webhook_url_env (default ${DEFAULT_WEBHOOK_ENV})"
        ),
    )
    parser.add_argument(
        "--webhook-env",
        metavar="ENV_NAME",
        default=None,
        help=(
            "Environment variable holding the webhook URL for --trigger "
            "(e.g. per-language webhooks). Takes precedence over "
            "teams.webhook_url_env; an explicit webhook_url argument still wins."
        ),
    )
    add_data_dir_arguments(parser)
    add_log_level_argument(parser)
    args = parser.parse_args()

    if args.date is not None:
        try:
            args.date = datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            console.print(
                f"[bold red]Invalid --date {args.date!r}; expected YYYY-MM-DD[/bold red]"
            )
            sys.exit(1)
        if args.hours is not None:
            console.print(
                "[bold red]--date and --hours are mutually exclusive[/bold red]"
            )
            sys.exit(1)

    if args.json_md is not None or args.trigger is not None:
        if args.date is not None or args.hours is not None:
            console.print(
                "[bold red]--json/--trigger are file operations and cannot be "
                "combined with --date/--hours[/bold red]"
            )
            sys.exit(1)
        sys.exit(_run_teams_command(args, icons))

    configure_logging(console, level=args.log_level)

    try:
        # Load environment variables from .env file
        load_dotenv()

        data_dir = Path(args.data_dir)

        # Initialize storage manager
        storage = StorageManager(data_dir=str(data_dir), config_path=args.config)

        # Load configuration
        try:
            config = storage.load_config()
        except FileNotFoundError:
            console.print(
                f"[bold red]{icons['error']} Configuration file not found![/bold red]\n"
            )
            console.print(f"Expected config: [cyan]{storage.config_path}[/cyan]\n")

            example_path = data_dir / "config.example.json"
            if not example_path.exists():
                example_path = Path("data/config.example.json")
            if example_path.exists():
                target_parent = storage.config_path.parent
                if target_parent != Path("."):
                    console.print(
                        f"Create the destination directory:\n"
                        f"  [cyan]mkdir -p {shlex.quote(str(target_parent))}[/cyan]\n"
                    )
                console.print(
                    f"Copy the example config and edit it:\n"
                    f"  [cyan]cp {shlex.quote(str(example_path))} "
                    f"{shlex.quote(str(storage.config_path))}[/cyan]\n"
                )
            if args.config is None and data_dir == Path("data"):
                console.print(
                    "Or run [bold cyan]uv run horizon-wizard[/bold cyan] to launch the interactive setup wizard.\n"
                )
            sys.exit(1)
        except ConfigError as e:
            console.print(
                f"[bold red]{icons['error']} Error loading configuration: {e}[/bold red]"
            )
            sys.exit(1)
        except Exception as e:
            console.print(
                f"[bold red]{icons['error']} Error loading configuration: {e}[/bold red]"
            )
            sys.exit(1)

        icons = get_icons(config.display.icon_style)

        # Create and run orchestrator
        orchestrator = HorizonOrchestrator(config, storage, console=console)
        notify = args.date is None or args.notify
        asyncio.run(
            orchestrator.run(force_hours=args.hours, date=args.date, notify=notify)
        )

    except KeyboardInterrupt:
        console.print(f"\n[yellow]{icons['warning']} Interrupted by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]{icons['error']} Fatal error: {e}[/bold red]")
        console.print_exception()
        sys.exit(1)


def _run_teams_command(args, icons) -> int:
    """Handle ``horizon --json`` / ``horizon --trigger`` without running the pipeline."""
    load_dotenv()
    data_dir = Path(args.data_dir)

    # Config supplies defaults (viewer base URL, webhook env var name).
    # A missing default config is only fatal when explicitly requested.
    try:
        config = StorageManager(data_dir=str(data_dir), config_path=args.config).load_config()
    except FileNotFoundError:
        if args.config is not None:
            console.print(
                f"[bold red]{icons['error']} Configuration file not found: {args.config}[/bold red]\n"
            )
            return 1
        config = None
    except Exception as e:
        console.print(
            f"[bold red]{icons['error']} Error loading configuration: {e}[/bold red]\n"
        )
        return 1
    teams_cfg = config.teams if config is not None else None

    exit_code = 0
    if args.json_md is not None:
        exit_code = _teams_json(args, data_dir, teams_cfg, icons)
    if exit_code == 0 and args.trigger is not None:
        exit_code = _teams_trigger(args, teams_cfg, icons)
    return exit_code


def _teams_json(args, data_dir: Path, teams_cfg, icons) -> int:
    """Convert a summary markdown file into a Teams Adaptive Card JSON file."""
    md_path = Path(args.json_md)
    if not md_path.is_file():
        console.print(f"[bold red]{icons['error']} markdown not found: {md_path}[/bold red]")
        return 1
    viewer_base = args.viewer_base or (teams_cfg.viewer_base_url if teams_cfg else None)
    if not viewer_base:
        console.print(
            "[bold red]no viewer base URL: pass --viewer-base or set "
            "teams.viewer_base_url in the config[/bold red]"
        )
        return 2
    lang = args.lang
    if not lang:
        m = re.search(r"horizon-\d{4}-\d{2}-\d{2}-([a-z]{2,3})\.md$", md_path.name)
        if not m:
            console.print(
                "[bold red]cannot infer --lang from file name; pass --lang explicitly[/bold red]"
            )
            return 2
        lang = m.group(1)

    md = md_path.read_text(encoding="utf-8")
    parsed = parse_summary(md)
    if not parsed["sections"]:
        console.print("[bold red]no ## sections with items found in markdown[/bold red]")
        return 2
    card = build_card(parsed, viewer_base, lang, top=args.top)

    out = Path(args.output) if args.output else data_dir / "teams" / (md_path.stem + ".json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    n_items = sum(len(s["items"]) for s in parsed["sections"])
    console.print(
        f"[green]{icons['success']} wrote Teams adaptive card: {out} "
        f"({len(parsed['sections'])} categories, {n_items} items)[/green]"
    )
    return 0


def _teams_trigger(args, teams_cfg, icons) -> int:
    """POST a Teams Adaptive Card JSON file to a webhook."""
    values = args.trigger
    if len(values) not in (1, 2):
        console.print("[bold red]--trigger expects <card_json> [webhook_url][/bold red]")
        return 2
    json_path = Path(values[0])
    if not json_path.is_file():
        console.print(f"[bold red]{icons['error']} card JSON not found: {json_path}[/bold red]")
        return 1
    try:
        card = normalize_card(json.loads(json_path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError) as e:
        console.print(f"[bold red]invalid card JSON: {e}[/bold red]")
        return 1

    webhook = values[1] if len(values) == 2 else None
    if not webhook and args.webhook_env:
        webhook = os.environ.get(args.webhook_env)
    if not webhook:
        env_name = (teams_cfg.webhook_url_env if teams_cfg else None) or DEFAULT_WEBHOOK_ENV
        webhook = os.environ.get(env_name)
        if not webhook:
            console.print(
                f"[yellow]{icons['warning']} no webhook URL (pass it as the second --trigger "
                f"arg or set ${env_name}); skipping send[/yellow]"
            )
            return 0

    resp = post_card(card, webhook)
    if is_success(resp.status_code):
        console.print(f"[green]{icons['success']} sent card to webhook (HTTP {resp.status_code})[/green]")
        return 0
    console.print(
        f"[bold red]{icons['error']} webhook returned HTTP {resp.status_code}: {resp.text[:300]}[/bold red]"
    )
    return 1


def print_config_template():
    """Print configuration template."""
    template = """
{
  "ai": {
    "provider": "anthropic",
    "model": "claude-sonnet-4.5-20250929",
    "api_key_env": "ANTHROPIC_API_KEY",
    "temperature": 0.3,
    "max_tokens": 4096
  },
  "display": {
    "icon_style": "emoji"
  },
  "sources": {
    "github": [
      {
        "type": "user_events",
        "username": "torvalds",
        "enabled": true,
        "profile": "tech-news"
      }
    ],
    "hackernews": {
      "enabled": true,
      "fetch_top_stories": 30,
      "min_score": 100,
      "profile": "tech-news"
    },
    "rss": [
      {
        "name": "Example Blog",
        "url": "https://example.com/feed.xml",
        "enabled": true,
        "category": "software-engineering",
        "profile": "auto"
      }
    ]
  },
  "collection": {
    "time_window_hours": 24
  },
  "digest": {
    "max_items": null,
    "profile_order": [
      "tech-news",
      "tech-blog",
      "finance-news"
    ],
    "category_groups": {},
    "default_group": "other",
    "default_group_limit": null
  },
  "processing": {
    "profiles_dir": "profiles",
    "default_profile": "tech-news",
    "profile_settings": {
      "tech-news": {
        "threshold": 7.0,
        "topic_dedup": true
      },
      "tech-blog": {
        "threshold": 4.0,
        "topic_dedup": false
      },
      "finance-news": {
        "threshold": 7.0,
        "topic_dedup": true
      }
    }
  }
}

Also create a .env file with:
ANTHROPIC_API_KEY=your_api_key_here
GITHUB_TOKEN=your_github_token_here (optional but recommended)
"""
    console.print(template)


if __name__ == "__main__":
    main()
