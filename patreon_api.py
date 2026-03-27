import re
import time
import logging
from urllib.parse import urlparse, unquote
import requests

logger = logging.getLogger("patreon_dl")


class AuthenticationError(Exception):
    pass


class PatreonAPI:
    BASE_URL = "https://www.patreon.com"

    def __init__(self, session_id: str, request_delay: float = 1.0):
        self.request_delay = request_delay
        self.session = requests.Session()
        self.session.cookies.set("session_id", session_id, domain=".patreon.com")
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.patreon.com/",
        })

    def validate_session(self) -> str:
        """Validate the session cookie. Returns the user's name or raises AuthenticationError."""
        resp = self.session.get(f"{self.BASE_URL}/api/current_user")
        if resp.status_code in (401, 403):
            raise AuthenticationError(
                "Session cookie is invalid or expired. Please update session_id in config.json.\n"
                "How to get it: Browser DevTools > Application > Cookies > patreon.com > session_id"
            )
        resp.raise_for_status()
        data = resp.json()
        name = data.get("data", {}).get("attributes", {}).get("full_name", "Unknown")
        logger.info(f"Authenticated as: {name}")
        return name

    def get_campaign_id(self, creator_vanity: str) -> str:
        """Resolve campaign_id from creator vanity URL name."""
        resp = self.session.get(f"{self.BASE_URL}/{creator_vanity}")
        resp.raise_for_status()

        # Try multiple patterns to extract campaign_id from page source
        patterns = [
            r'"campaign":\s*\{\s*"data":\s*\{\s*"id":\s*"(\d+)"',
            r'"campaign_id":\s*(\d+)',
            r'/campaign/(\d+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, resp.text)
            if match:
                campaign_id = match.group(1)
                logger.info(f"Resolved campaign_id: {campaign_id} for creator: {creator_vanity}")
                return campaign_id

        raise RuntimeError(
            f"Could not extract campaign_id from {creator_vanity}'s page. "
            "The page structure may have changed."
        )

    def _build_posts_url(self, campaign_id: str) -> str:
        """Build the initial posts API URL with all required fields."""
        params = (
            "include=campaign,attachments,attachments_media,media,user"
            "&fields[post]=content,embed,image,published_at,title,url,patreon_url,"
            "post_file,post_type,current_user_can_view"
            "&fields[media]=id,download_url,file_name,image_urls,metadata"
            "&fields[campaign]=name,url"
            "&fields[user]=full_name,url"
            f"&filter[campaign_id]={campaign_id}"
            "&filter[is_draft]=false"
            "&sort=-published_at"
            "&page[count]=20"
            "&json-api-version=1.0"
        )
        return f"{self.BASE_URL}/api/posts?{params}"

    def _request_with_retry(self, url: str, max_retries: int = 3) -> dict:
        """Make a GET request with retry logic for rate limiting and server errors."""
        for attempt in range(max_retries):
            time.sleep(self.request_delay)
            resp = self.session.get(url)

            if resp.status_code == 200:
                return resp.json()

            if resp.status_code in (401, 403):
                raise AuthenticationError(
                    "Session expired during download. Please update session_id in config.json."
                )

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                logger.warning(f"Rate limited. Waiting {retry_after}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_after)
                continue

            if resp.status_code >= 500:
                wait = 2 ** attempt * 5
                logger.warning(f"Server error {resp.status_code}. Waiting {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
                continue

            resp.raise_for_status()

        raise RuntimeError(f"Failed to fetch {url} after {max_retries} retries")

    def iter_posts(self, campaign_id: str):
        """Yield parsed post dicts for all posts in a campaign, newest first."""
        url = self._build_posts_url(campaign_id)
        page = 0

        while url:
            page += 1
            logger.debug(f"Fetching page {page}: {url[:120]}...")
            data = self._request_with_retry(url)

            # Build lookup of included resources by (type, id)
            included = {}
            for item in data.get("included", []):
                included[(item["type"], item["id"])] = item

            for post_data in data.get("data", []):
                yield self._parse_post(post_data, included)

            # Follow pagination cursor
            url = data.get("links", {}).get("next")

        logger.info(f"Finished fetching all posts ({page} pages)")

    def _parse_post(self, post_data: dict, included: dict) -> dict:
        """Transform raw JSON:API post into a clean dictionary."""
        attrs = post_data.get("attributes", {})
        relationships = post_data.get("relationships", {})

        post = {
            "id": post_data["id"],
            "title": attrs.get("title") or "Untitled",
            "published_at": attrs.get("published_at"),
            "url": attrs.get("url") or attrs.get("patreon_url") or "",
            "post_type": attrs.get("post_type"),
            "can_view": attrs.get("current_user_can_view", False),
            "content": attrs.get("content") or "",
            "youtube_urls": [],
            "attachments": [],
        }

        # Extract YouTube URL from embed field
        embed = attrs.get("embed")
        if embed and isinstance(embed, dict):
            embed_url = embed.get("url", "")
            if "youtube.com" in embed_url or "youtu.be" in embed_url:
                post["youtube_urls"].append(embed_url)

        # Also scan HTML content for YouTube links not in embed
        from utils import extract_youtube_urls
        for yt_url in extract_youtube_urls(post["content"]):
            if yt_url not in post["youtube_urls"]:
                post["youtube_urls"].append(yt_url)

        # Extract post_file (direct file on the post)
        post_file = attrs.get("post_file")
        if post_file and isinstance(post_file, dict) and post_file.get("url"):
            name = post_file.get("name") or "post_file"
            # If name has no extension, try to get one from the URL
            if "." not in name:
                url_path = urlparse(post_file["url"]).path
                url_filename = unquote(url_path.rsplit("/", 1)[-1])
                if "." in url_filename:
                    name = url_filename
            post["attachments"].append({
                "url": post_file["url"],
                "name": name,
            })

        # Extract attachments and media from relationships
        for rel_name in ("attachments", "attachments_media", "media"):
            rel = relationships.get(rel_name, {})
            rel_data = rel.get("data") if isinstance(rel, dict) else None
            if not rel_data:
                continue
            if isinstance(rel_data, dict):
                rel_data = [rel_data]
            for ref in rel_data:
                if not isinstance(ref, dict):
                    continue
                key = (ref.get("type"), ref.get("id"))
                resource = included.get(key, {})
                res_attrs = resource.get("attributes", {})
                url = res_attrs.get("download_url") or res_attrs.get("url")
                name = res_attrs.get("file_name") or res_attrs.get("name")
                if url and name:
                    # Avoid duplicates
                    if not any(a["url"] == url for a in post["attachments"]):
                        post["attachments"].append({"url": url, "name": name})

        return post
