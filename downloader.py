import json
import re
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from patreon_api import PatreonAPI
from youtube import download_youtube
from utils import make_folder_name, sanitize_filename

logger = logging.getLogger("patreon_dl")


def load_state(state_path: Path) -> dict:
    """Load resume state from disk."""
    if state_path.exists():
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"completed": set(data.get("completed_post_ids", []))}
    return {"completed": set()}


def save_state(state_path: Path, state: dict):
    """Save resume state to disk."""
    data = {"completed_post_ids": sorted(state["completed"])}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def load_failed(failed_path: Path) -> dict:
    """Load failed posts registry from disk. Returns {post_id: entry_dict}."""
    if failed_path.exists():
        with open(failed_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {entry["post_id"]: entry for entry in data.get("failed_posts", [])}
    return {}


def save_failed(failed_path: Path, failed: dict):
    """Save failed posts registry to disk."""
    data = {"failed_posts": list(failed.values())}
    failed_path.parent.mkdir(parents=True, exist_ok=True)
    with open(failed_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update_failed(failed_path: Path, failed: dict, post: dict,
                   folder_name: str, errors: list):
    """Add/update/remove a post in the failed registry based on errors."""
    if errors:
        failed[post["id"]] = {
            "post_id": post["id"],
            "post_url": post["url"],
            "title": post["title"],
            "folder": folder_name,
            "errors": errors,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    elif post["id"] in failed:
        del failed[post["id"]]
    save_failed(failed_path, failed)


def download_file(session, url: str, filepath: Path, max_retries: int = 3) -> tuple:
    """Download a file with streaming and retry logic.

    Returns (success: bool, error_message: str).
    """
    if filepath.exists():
        logger.debug(f"Skipping existing file: {filepath.name}")
        return True, ""

    for attempt in range(max_retries):
        try:
            resp = session.get(url, stream=True, timeout=120)
            resp.raise_for_status()

            temp_path = filepath.with_suffix(filepath.suffix + ".tmp")
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            temp_path.rename(filepath)
            logger.debug(f"Downloaded: {filepath.name}")
            return True, ""

        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt * 2
                logger.warning(f"Retry {attempt + 1}/{max_retries} for {filepath.name}: {e}")
                time.sleep(wait)
                # Clean up partial temp file
                temp_path = filepath.with_suffix(filepath.suffix + ".tmp")
                if temp_path.exists():
                    temp_path.unlink()
                continue
            return False, str(e)

    return False, "Max retries exceeded"


def write_info_txt(post_dir: Path, post: dict, errors: list):
    """Write metadata info.txt for a post."""
    lines = [
        f"Title: {post['title']}",
        f"Published: {post['published_at'] or 'unknown'}",
        f"URL: {post['url']}",
        f"Post Type: {post['post_type'] or 'unknown'}",
        "",
    ]

    if post["youtube_urls"]:
        for yt_url in post["youtube_urls"]:
            lines.append(f"YouTube: {yt_url}")
    else:
        lines.append("YouTube: (none)")

    attachment_names = [a["name"] for a in post["attachments"]]
    lines.append(f"Attachments: {', '.join(attachment_names) if attachment_names else '(none)'}")

    lines.append("")
    lines.append("--- Errors ---")
    if errors:
        for err in errors:
            lines.append(err)
    else:
        lines.append("(none)")

    info_path = post_dir / "info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def write_content_html(post_dir: Path, content: str):
    """Save the post's HTML body content."""
    if not content or not content.strip():
        return
    content_path = post_dir / "content.html"
    with open(content_path, "w", encoding="utf-8") as f:
        f.write(content)


def _parse_vanity(creator_url: str) -> str:
    """Extract creator vanity name from a Patreon URL."""
    parts = creator_url.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if part == "c" and i + 1 < len(parts):
            return parts[i + 1]
    for i, part in enumerate(parts):
        if "patreon.com" in part and i + 1 < len(parts):
            return parts[i + 1]
    raise RuntimeError(f"Could not parse creator vanity from URL: {creator_url}")


def _setup_output(config: dict, api: PatreonAPI):
    """Common setup: parse vanity, resolve campaign, prepare output paths.

    Returns (vanity, campaign_id, output_dir, state_path, failed_path, state, failed).
    """
    vanity = _parse_vanity(config["creator_url"])
    logger.info(f"Creator vanity: {vanity}")

    campaign_id = api.get_campaign_id(vanity)

    output_dir = Path(config.get("output_dir", "./output")) / vanity
    output_dir.mkdir(parents=True, exist_ok=True)
    state_path = output_dir / "_state.json"
    failed_path = output_dir / "_failed.json"
    state = load_state(state_path)
    failed = load_failed(failed_path)

    return vanity, campaign_id, output_dir, state_path, failed_path, state, failed


def _download_post(post: dict, post_dir: Path, folder_name: str, config: dict,
                   api: PatreonAPI, state: dict, state_path: Path,
                   failed: dict, failed_path: Path) -> list:
    """Download a single post's content. Returns list of error strings."""
    post_dir.mkdir(parents=True, exist_ok=True)
    ytdlp_path = config.get("ytdlp_path", "./yt-dlp.exe")
    cookies_file = config.get("youtube_cookies")
    errors = []

    for yt_url in post["youtube_urls"]:
        success, error = download_youtube(yt_url, post_dir, ytdlp_path,
                                          cookies_file=cookies_file)
        if not success:
            errors.append(f"YouTube download failed ({yt_url}): {error}")

    for attachment in post["attachments"]:
        att_name = attachment["name"]
        # If name looks like a URL, extract the last path segment
        if att_name.startswith("http://") or att_name.startswith("https://"):
            from urllib.parse import urlparse, unquote
            att_name = unquote(urlparse(att_name).path.rsplit("/", 1)[-1]) or "attachment"
        safe_name = sanitize_filename(att_name)
        # Preserve the original file extension
        if "." in att_name:
            ext = att_name.rsplit(".", 1)[-1]
            if len(ext) <= 10 and not safe_name.endswith(f".{ext}"):
                safe_name = f"{safe_name}.{ext}"
        filepath = post_dir / safe_name
        success, error = download_file(api.session, attachment["url"], filepath)
        if not success:
            errors.append(f"Attachment '{attachment['name']}' failed: {error}")

    write_content_html(post_dir, post["content"])
    write_info_txt(post_dir, post, errors)

    state["completed"].add(post["id"])
    save_state(state_path, state)
    update_failed(failed_path, failed, post, folder_name, errors)

    return errors


def download_all(config: dict, api: PatreonAPI, dry_run: bool = False):
    """Main download loop. Processes all posts for a creator."""
    vanity, campaign_id, output_dir, state_path, failed_path, state, failed = \
        _setup_output(config, api)

    logger.info(f"Output directory: {output_dir}")
    logger.info(f"Previously completed: {len(state['completed'])} posts")
    if failed:
        logger.info(f"Previously failed: {len(failed)} posts (use --retry to re-attempt)")

    # Collect all posts (API returns newest-first, we want oldest-first)
    logger.info("Fetching post list...")
    all_posts = list(api.iter_posts(campaign_id))
    all_posts.reverse()  # Now oldest first
    logger.info(f"Total posts: {len(all_posts)}")

    if dry_run:
        _print_dry_run(all_posts, state, failed)
        return

    downloaded = 0
    skipped = 0
    errored = 0

    for idx, post in enumerate(all_posts, start=1):
        if post["id"] in state["completed"]:
            skipped += 1
            continue

        if not post["can_view"]:
            logger.warning(f"[{idx}/{len(all_posts)}] Cannot view (access restricted): {post['title']}")
            continue

        folder_name = make_folder_name(idx, post["published_at"], post["title"])
        post_dir = output_dir / folder_name

        logger.info(f"[{idx}/{len(all_posts)}] Downloading: {post['title']}")
        errors = _download_post(post, post_dir, folder_name, config, api,
                                state, state_path, failed, failed_path)

        if errors:
            errored += 1
            for err in errors:
                logger.warning(f"  Error: {err}")
        else:
            downloaded += 1

    # Summary
    logger.info("=" * 50)
    logger.info(f"Download complete!")
    logger.info(f"  Downloaded: {downloaded}")
    logger.info(f"  Skipped (already done): {skipped}")
    logger.info(f"  With errors: {errored}")
    logger.info(f"  Total posts: {len(all_posts)}")
    if failed:
        logger.info(f"  Failed posts logged in: {failed_path}")


def _print_dry_run(all_posts: list, state: dict, failed: dict):
    """Print post list without downloading."""
    logger.info("=" * 50)
    logger.info("DRY RUN - No files will be downloaded")
    logger.info("=" * 50)

    new_count = 0
    fail_count = 0
    for idx, post in enumerate(all_posts, start=1):
        if post["id"] in failed:
            status = "FAIL"
            fail_count += 1
        elif post["id"] in state["completed"]:
            status = "DONE"
        else:
            status = " NEW"
            new_count += 1
        view = "OK" if post["can_view"] else "LOCKED"

        yt = len(post["youtube_urls"])
        att = len(post["attachments"])
        date = (post["published_at"] or "")[:10]

        logger.info(
            f"  [{status}] [{view}] {idx:4d}. {date} | "
            f"YT:{yt} Files:{att} | {post['title'][:60]}"
        )

    logger.info("=" * 50)
    logger.info(f"Total: {len(all_posts)} posts, {new_count} new, {fail_count} failed")


def retry_failed(config: dict, api: PatreonAPI):
    """Retry all previously failed posts."""
    vanity, campaign_id, output_dir, state_path, failed_path, state, failed = \
        _setup_output(config, api)

    if not failed:
        logger.info("No failed posts to retry.")
        return

    logger.info(f"Retrying {len(failed)} failed post(s)...")

    # Fetch all posts to get current download URLs
    logger.info("Fetching post list...")
    all_posts = list(api.iter_posts(campaign_id))
    all_posts.reverse()
    posts_by_id = {p["id"]: p for p in all_posts}

    # Build index mapping to get correct folder numbering
    succeeded = 0
    still_failed = 0

    for post_id, entry in list(failed.items()):
        post = posts_by_id.get(post_id)
        if not post:
            logger.warning(f"Post {post_id} ('{entry['title']}') no longer found in API, skipping")
            continue

        # Find existing folder on disk
        folder_name = entry["folder"]
        post_dir = output_dir / folder_name
        if not post_dir.exists():
            # Folder may have been renamed; scan for it
            post_dir = _find_post_folder(output_dir, post)
            if post_dir:
                folder_name = post_dir.name
            else:
                # Create new folder using the stored name
                post_dir = output_dir / folder_name

        logger.info(f"Retrying: {post['title']} -> {folder_name}")
        errors = _download_post(post, post_dir, folder_name, config, api,
                                state, state_path, failed, failed_path)

        if errors:
            still_failed += 1
            for err in errors:
                logger.warning(f"  Still failing: {err}")
        else:
            succeeded += 1
            logger.info(f"  Resolved!")

    logger.info("=" * 50)
    logger.info(f"Retry complete! Resolved: {succeeded}, still failing: {still_failed}")


def retry_single_post(config: dict, api: PatreonAPI, post_ref: str):
    """Retry a single post by URL or ID."""
    vanity, campaign_id, output_dir, state_path, failed_path, state, failed = \
        _setup_output(config, api)

    # Parse post ID from URL or bare ID
    post_id = _parse_post_ref(post_ref)

    # Fetch all posts to find this one and determine its index
    logger.info("Fetching post list...")
    all_posts = list(api.iter_posts(campaign_id))
    all_posts.reverse()

    target_post = None
    target_idx = None
    for idx, post in enumerate(all_posts, start=1):
        if post["id"] == post_id:
            target_post = post
            target_idx = idx
            break

    if not target_post:
        logger.error(f"Post '{post_ref}' (ID: {post_id}) not found in campaign")
        return

    # Find existing folder or create one
    folder_name = None
    post_dir = _find_post_folder(output_dir, target_post)
    if post_dir:
        folder_name = post_dir.name
    else:
        folder_name = make_folder_name(target_idx, target_post["published_at"],
                                       target_post["title"])
        post_dir = output_dir / folder_name

    logger.info(f"Retrying post: {target_post['title']} -> {folder_name}")
    errors = _download_post(target_post, post_dir, folder_name, config, api,
                            state, state_path, failed, failed_path)

    if errors:
        for err in errors:
            logger.warning(f"  Error: {err}")
        logger.info("Post still has errors.")
    else:
        logger.info("Post downloaded successfully!")


def _parse_post_ref(ref: str) -> str:
    """Extract a post ID from a URL like 'https://www.patreon.com/posts/title-12345' or bare '12345'."""
    # Try bare numeric ID
    if ref.isdigit():
        return ref
    # Try URL: last segment is 'slug-12345', ID is the trailing digits
    match = re.search(r'(\d+)\s*$', ref.rstrip("/").split("/")[-1])
    if match:
        return match.group(1)
    raise RuntimeError(f"Could not parse post ID from: {ref}")


def _find_post_folder(output_dir: Path, post: dict):
    """Find an existing folder for a post by scanning info.txt files for matching URL."""
    post_url = post["url"]
    for info_path in output_dir.glob("*/info.txt"):
        try:
            text = info_path.read_text(encoding="utf-8")
            if f"URL: {post_url}" in text:
                return info_path.parent
        except OSError:
            continue
    return None
