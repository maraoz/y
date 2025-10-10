# x.py

A minimal X (Twitter) API v2 CLI tool. Vibe-coded with Claude.

## Install

```bash
pip install requests requests-oauthlib
```

## Setup

Create a `config.py` file with your X API credentials:

```python
X_API_KEY = "your_api_key_here"
X_API_SECRET = "your_api_secret_here"
X_ACCESS_TOKEN = "your_access_token_here"
X_ACCESS_TOKEN_SECRET = "your_access_token_secret_here"
```

Get credentials from the [X Developer Portal](https://developer.x.com/).

## Usage

**Interactive menu (recommended):**
```bash
./x.py
```
Navigate with arrow keys, press Enter to select.

**Direct commands:**
```bash
./x.py post                         # Post a tweet (prompts for text in TUI)
./x.py post "Hello world"           # Post a tweet directly
./x.py mentions                     # List mentions
./x.py interact                     # Reply to mentions (interactive)
./x.py thread                       # Build threads (interactive)
./x.py timeline                     # View timeline
./x.py engagement                   # View engagement metrics
```

## How it works

All commands use interactive TUI with arrow key navigation:

- **mentions**: Browse mentions, press ENTER for details (tracks unread)
- **interact**: Browse mentions and reply to them
- **thread**: Browse your tweets and build threads
- **timeline**: Browse tweets from people you follow
- **engagement**: Browse your tweets with engagement metrics
- **post**: Publish tweets (with optional reply threading)

**Navigation:**
- `↑/↓` - Navigate list
- `ENTER` - View details (mentions/timeline/engagement) or compose reply (interact/thread)
- `ESC` - Back to list (from detail view)
- `q` - Quit
