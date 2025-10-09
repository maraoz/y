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

```bash
# Post a tweet
./x.py post "Hello world"

# List mentions
./x.py mentions

# Interactive UI to browse and reply to mentions
./x.py interact

# View engagement metrics
./x.py engagements
```

## How it works

- **mentions**: Tracks unread mentions using a local state file
- **interact**: Curses-based TUI with arrow key navigation and inline replies
- **engagements**: Shows public metrics for your recent tweets
- **post**: Publishes tweets with optional reply threading
