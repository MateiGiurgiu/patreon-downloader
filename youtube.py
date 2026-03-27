import subprocess
import logging
from pathlib import Path

logger = logging.getLogger("patreon_dl")


def download_youtube(url: str, output_dir: Path, ytdlp_path: str,
                     format_str: str = None,
                     cookies_file: str = None) -> tuple:
    """Download a YouTube video using yt-dlp subprocess.

    Returns (success: bool, error_message: str).
    """
    fmt = format_str or "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]"
    cmd = [
        str(ytdlp_path),
        "--no-playlist",
        "-f", fmt,
        "-o", str(output_dir / "%(title)s.%(ext)s"),
        "--no-overwrites",
        "--merge-output-format", "mp4",
    ]
    if cookies_file:
        cmd.extend(["--cookies", str(cookies_file)])
    cmd.append(url)

    logger.debug(f"Running yt-dlp: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=600
        )
        if result.returncode == 0:
            logger.debug(f"yt-dlp success for {url}")
            return True, ""
        else:
            error = result.stderr.strip() or result.stdout.strip()
            logger.warning(f"yt-dlp failed for {url}: {error[:200]}")
            return False, error
    except subprocess.TimeoutExpired:
        msg = "Download timed out after 600 seconds"
        logger.warning(f"yt-dlp timeout for {url}")
        return False, msg
    except FileNotFoundError:
        msg = f"yt-dlp not found at: {ytdlp_path}"
        logger.error(msg)
        return False, msg
