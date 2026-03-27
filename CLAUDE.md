# Patreon Downloader

## Overview
Downloads all posts from a Patreon creator (built for 3D Extrude Tutorials). Grabs YouTube videos via yt-dlp and file attachments (.sbs, .zip), organizes into per-post folders with metadata.

## Setup
```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
```

## Usage
1. Copy your Patreon `session_id` cookie into `config.json`
2. Export YouTube cookies via "Get cookies.txt LOCALLY" Chrome extension to `cookies.txt`
3. Place `yt-dlp.exe`, `ffmpeg.exe`, `ffprobe.exe` in the project root
4. Ensure Deno is installed (`winget install DenoLand.Deno`) — required by yt-dlp for YouTube
5. `python main.py` to download, `python main.py --dry-run` to preview
6. `python main.py --retry` to retry all previously failed posts
7. `python main.py --retry-post <URL_or_ID>` to retry a single post

## Architecture
- `main.py` — Entry point, config loading, CLI (argparse)
- `patreon_api.py` — Patreon API client (session cookie auth, pagination, JSON:API parsing)
- `downloader.py` — Download orchestration, folder creation, info.txt/content.html, state/failed tracking, retry logic
- `youtube.py` — yt-dlp subprocess wrapper (supports cookies file for YouTube auth)
- `utils.py` — Filename sanitization, YouTube URL extraction from HTML, logging setup

## Key Details
- Single external dependency: `requests`
- Auth via Patreon `session_id` cookie (browser DevTools > Application > Cookies)
- YouTube auth via Netscape-format `cookies.txt` (Chrome DPAPI broken on Win11, must use extension export)
- Posts sorted oldest-first (0001 = earliest)
- Resumable via `_state.json` tracking completed post IDs
- Failed posts tracked in `_failed.json` with post ID, URL, title, folder, errors, timestamp
- Retry modes: `--retry` (all failed) or `--retry-post <URL_or_ID>` (single post)
- 1s delay between API requests to avoid rate limiting
- Output directory configurable in `config.json` (supports UNC paths like `//Server/Share`)
- File downloads use streaming with 3 retries and exponential backoff
- YouTube download timeout: 600 seconds
- Attachment filenames are sanitized for Windows (colons, slashes, etc.)
- URL-as-filename fallback: extracts last path segment from URL when API returns no filename

## Config format (`config.json`)
```json
{
  "session_id": "...",
  "creator_url": "https://www.patreon.com/c/CREATOR/posts",
  "output_dir": "./output",
  "ytdlp_path": "./yt-dlp.exe",
  "youtube_cookies": "./cookies.txt",
  "request_delay_seconds": 1.0
}
```

## Known issues / things that can break
- Patreon `session_id` expires periodically — user must re-copy from browser
- YouTube cookies expire — must re-export via Chrome extension
- yt-dlp requires a JavaScript runtime (Deno recommended) for YouTube nsig extraction
- Some Patreon attachments have no filename in API, only a URL — handled by extracting last path segment
- Campaign ID extraction uses regex on page HTML — may break if Patreon changes page structure
- Chrome on Windows 11: `--cookies-from-browser chrome` does NOT work due to Application Bound Encryption (DPAPI)
