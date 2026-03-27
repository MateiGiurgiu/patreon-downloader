import re
import logging
import sys
from pathlib import Path

YOUTUBE_PATTERNS = [
    re.compile(r'https?://(?:www\.)?youtube\.com/watch\?v=([\w-]+)'),
    re.compile(r'https?://youtu\.be/([\w-]+)'),
    re.compile(r'https?://(?:www\.)?youtube\.com/embed/([\w-]+)'),
]


def extract_youtube_urls(text: str) -> list:
    """Extract unique YouTube URLs from HTML or plain text."""
    urls = []
    seen = set()
    for pattern in YOUTUBE_PATTERNS:
        for match in pattern.finditer(text):
            video_id = match.group(1)
            if video_id not in seen:
                seen.add(video_id)
                urls.append(f"https://www.youtube.com/watch?v={video_id}")
    return urls


def sanitize_filename(name: str) -> str:
    """Remove/replace characters invalid in Windows filenames."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '-', name)
    cleaned = re.sub(r'-+', '-', cleaned).strip('-').strip()
    cleaned = cleaned.strip('.')
    return cleaned or "untitled"


def make_folder_name(number: int, published_at: str, title: str) -> str:
    """Create folder name like: 0001_2024-01-15_post-title-slug"""
    date_str = published_at[:10] if published_at else "unknown-date"
    slug = sanitize_filename(title)[:60]
    return f"{number:04d}_{date_str}_{slug}"


def setup_logging(log_file: Path = None) -> logging.Logger:
    """Configure logging to console and optionally to file."""
    logger = logging.getLogger("patreon_dl")
    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(console)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(str(log_file), encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        logger.addHandler(fh)

    return logger
