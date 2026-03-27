# Patreon Downloader

Downloads all posts from a Patreon creator you're subscribed to. Grabs YouTube videos via yt-dlp and file attachments (.sbs, .zip, etc.), organizing everything into per-post folders with metadata.

Built for archiving tutorial content (Substance Designer, Maya/ZBrush, Substance Painter), but works with any Patreon creator.

## Prerequisites

- **Python 3.10+** (with pip)
- **yt-dlp** — download the latest `yt-dlp.exe` from [yt-dlp releases](https://github.com/yt-dlp/yt-dlp/releases/latest) and place it in the project root
- **FFmpeg** — required by yt-dlp for merging video+audio. Use the [yt-dlp custom FFmpeg builds](https://github.com/yt-dlp/FFmpeg-Builds#ffmpeg-static-auto-builds) (patched for yt-dlp compatibility, **not** the Python package). Place `ffmpeg.exe` and `ffprobe.exe` in the project root
- **Deno** (or Node.js) — JavaScript runtime required by yt-dlp for YouTube downloads. Install via `winget install DenoLand.Deno`
- **A Patreon subscription** to the creator you want to download from

## Setup

```bash
# Clone the repo
git clone https://github.com/youruser/patreon-downloader.git
cd patreon-downloader

# Create virtual environment and install dependencies
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
# Or on PowerShell: .venv\Scripts\activate
pip install -r requirements.txt
```

On first run, a template `config.json` will be created. Fill it in:

```json
{
  "session_id": "PASTE_YOUR_SESSION_ID_COOKIE_HERE",
  "creator_url": "https://www.patreon.com/c/CREATOR_NAME/posts",
  "output_dir": "./output",
  "ytdlp_path": "./yt-dlp.exe",
  "youtube_cookies": "./cookies.txt",
  "request_delay_seconds": 1.0
}
```

### Config fields

| Field | Description |
|---|---|
| `session_id` | Your Patreon session cookie (see below) |
| `creator_url` | The Patreon creator's posts page URL |
| `output_dir` | Where to save downloads. Supports UNC paths (`//Server/Share/path`) |
| `ytdlp_path` | Path to the yt-dlp binary |
| `youtube_cookies` | Path to a Netscape-format cookies.txt for YouTube (see below) |
| `request_delay_seconds` | Delay between Patreon API requests (default: 1.0s) |

## Authentication

### Patreon session cookie

1. Log into Patreon in your browser
2. Open DevTools (`F12`) > **Application** > **Cookies** > `patreon.com`
3. Copy the value of the `session_id` cookie
4. Paste it into `config.json`

The cookie expires periodically — you'll need to re-copy it when that happens.

### YouTube cookies (required for yt-dlp)

YouTube requires authentication to avoid bot detection. Since Chrome on Windows 11 uses Application Bound Encryption (which yt-dlp can't decrypt), you need to export cookies manually:

1. Install the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension (open source, no data sent externally)
2. Go to `youtube.com` (make sure you're logged in)
3. Click the extension icon and export cookies in **Netscape format**
4. Save the file as `cookies.txt` in the project root

Re-export whenever the cookies expire.

## Usage

```bash
# Activate the virtual environment first
source .venv/Scripts/activate   # Git Bash
# .venv\Scripts\activate        # PowerShell

# Preview what will be downloaded (no files touched)
python main.py --dry-run

# Download everything
python main.py

# Retry all previously failed posts
python main.py --retry

# Retry a single post by URL or ID
python main.py --retry-post "https://www.patreon.com/posts/some-title-12345"
python main.py --retry-post 12345

# Use a different config file
python main.py --config path/to/config.json
```

## How it works

1. Authenticates with Patreon using your session cookie
2. Fetches all posts from the creator via the Patreon API (paginated, 20 per page)
3. For each post (oldest first):
   - Creates a folder: `0001_2024-01-15_Post-Title/`
   - Downloads YouTube videos via yt-dlp (if any)
   - Downloads file attachments (.sbs, .zip, etc.)
   - Saves post HTML content as `content.html`
   - Writes metadata to `info.txt`
4. Tracks progress in `_state.json` (completed post IDs) — safe to interrupt and resume
5. Tracks failures in `_failed.json` for targeted retrying

## Output structure

```
output/
  CreatorName/
    _state.json              # Completed post IDs (resume tracking)
    _failed.json             # Failed posts (retry tracking)
    0001_2017-12-02_First-Post/
      info.txt               # Metadata + errors
      content.html           # Post HTML body
      Video Title.mp4        # YouTube download
      texture.sbs            # Attached files
    0002_2017-12-03_Second-Post/
      ...
```

### info.txt format

```
Title: Stylized Chest Tutorial!
Published: 2017-12-03T00:00:00.000000+00:00
URL: https://www.patreon.com/posts/...
Post Type: video_embed

YouTube: https://www.youtube.com/watch?v=...
Attachments: chest_texture.sbs

--- Errors ---
(none)
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `Session cookie is invalid or expired` | Re-copy `session_id` from browser DevTools |
| `Sign in to confirm you're not a bot` | Export fresh YouTube cookies (see above) |
| `Failed to decrypt with DPAPI` | Use the cookie extension method, not `--cookies-from-browser` |
| `yt-dlp not found` | Place `yt-dlp.exe` in the project root or update `ytdlp_path` in config |
| `nsig extraction failed` | Install Deno (`winget install DenoLand.Deno`) and restart terminal |
| Download times out | Default timeout is 600s. Some large videos may need a retry |
| Windows filename errors | Known issue with special characters — the downloader sanitizes filenames automatically |
