import json
import sys
import argparse
from pathlib import Path

from patreon_api import PatreonAPI, AuthenticationError
from downloader import download_all, retry_failed, retry_single_post
from utils import setup_logging

CONFIG_TEMPLATE = {
    "session_id": "PASTE_YOUR_SESSION_ID_COOKIE_HERE",
    "creator_url": "https://www.patreon.com/c/3dEx/posts",
    "output_dir": "./output",
    "ytdlp_path": "./yt-dlp.exe",
    "request_delay_seconds": 1.0,
}


def load_config(config_path: Path) -> dict:
    """Load config from JSON file, creating a template if it doesn't exist."""
    if not config_path.exists():
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(CONFIG_TEMPLATE, f, indent=2)
        print(f"Created config template at: {config_path}")
        print("Please edit it with your session_id cookie and run again.")
        print()
        print("How to get your session_id:")
        print("  1. Log into Patreon in your browser")
        print("  2. Open DevTools (F12) > Application > Cookies > patreon.com")
        print("  3. Copy the value of the 'session_id' cookie")
        print("  4. Paste it into config.json")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    if config.get("session_id") == "PASTE_YOUR_SESSION_ID_COOKIE_HERE":
        print("Error: Please update session_id in config.json with your Patreon cookie.")
        print()
        print("How to get your session_id:")
        print("  1. Log into Patreon in your browser")
        print("  2. Open DevTools (F12) > Application > Cookies > patreon.com")
        print("  3. Copy the value of the 'session_id' cookie")
        print("  4. Paste it into config.json")
        sys.exit(1)

    return config


def main():
    parser = argparse.ArgumentParser(description="Download content from Patreon creators")
    parser.add_argument("--config", default="config.json", help="Path to config file (default: config.json)")
    parser.add_argument("--dry-run", action="store_true", help="List posts without downloading")
    parser.add_argument("--retry", action="store_true", help="Retry all previously failed posts")
    parser.add_argument("--retry-post", metavar="URL_OR_ID",
                        help="Retry a single post by Patreon URL or post ID")
    args = parser.parse_args()

    config_path = Path(args.config)
    config = load_config(config_path)

    # Set up logging
    output_dir = Path(config.get("output_dir", "./output"))
    log_file = output_dir / "download.log"
    logger = setup_logging(log_file)

    # Validate yt-dlp path (unless dry run)
    ytdlp_path = Path(config.get("ytdlp_path", "./yt-dlp.exe"))
    if not args.dry_run and not ytdlp_path.exists():
        logger.warning(f"yt-dlp not found at: {ytdlp_path}")
        logger.warning("YouTube videos will fail to download. Place yt-dlp.exe in the project directory or update ytdlp_path in config.json.")

    # Initialize API client
    api = PatreonAPI(
        session_id=config["session_id"],
        request_delay=config.get("request_delay_seconds", 1.0),
    )

    # Validate session
    try:
        api.validate_session()
    except AuthenticationError as e:
        logger.error(str(e))
        sys.exit(1)

    # Run the requested mode
    try:
        if args.retry:
            retry_failed(config, api)
        elif args.retry_post:
            retry_single_post(config, api, args.retry_post)
        else:
            download_all(config, api, dry_run=args.dry_run)
    except AuthenticationError as e:
        logger.error(str(e))
        sys.exit(1)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Progress has been saved - run again to resume.")
        sys.exit(0)


if __name__ == "__main__":
    main()
