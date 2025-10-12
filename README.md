# ×

A minimal X (Twitter) CLI with full TUI navigation. Built with Claude.

## Features

- 🎨 Full terminal UI with arrow key navigation
- 📸 Image attachment support (Ctrl+V to paste from clipboard)
- 🔄 Thread building and replies
- 📊 Engagement metrics
- ⚡ Fast, responsive, stays in curses mode (no flashing)

## Install

```bash
pip install requests requests-oauthlib
```

**For image support (optional):**
```bash
brew install pngpaste  # macOS only
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

**Direct commands:**
```bash
./x.py timeline           # View timeline
./x.py post               # Compose tweet/thread
./x.py post "Hello"       # Post tweet directly
./x.py mentions           # View mentions (read-only)
./x.py interact           # Browse and reply to mentions
./x.py engagement         # View your tweets with metrics
```

## Navigation

### Main Menu
- **read** - Browse your timeline
- **write** - Compose new tweet or continue thread
- **mentions** - Browse and reply to mentions
- **ego** - View engagement metrics
- **exit** - Quit

### List Views
- `↑/↓` - Navigate between items
- `ENTER` - View details or compose reply
- `ESC` / `q` - Go back

### Detail Views
- `↑/↓` - Navigate between tweets without leaving detail view
- `ENTER` - Reply to tweet (mentions/interact only)
- `ESC` - Return to list

### Compose/Reply
- `ENTER` - New line
- `Ctrl+V` - Attach image from clipboard (up to 4 images)
- `Ctrl+D` - Send tweet
- `ESC` - Cancel

## How It Works

### read (timeline)
Browse tweets from people you follow. Navigate with arrows, press ENTER for full tweet view.

### write (post/thread)
- Select "new" to compose a fresh tweet
- Select a previous tweet to add to the thread
- Lazy loads your recent tweets in the background

### mentions (interact)
Browse mentions with full detail view. Press ENTER to reply in interact mode.

### ego (engagement)
View your recent tweets with likes, retweets, and replies.

## License

MIT License - see [LICENSE](LICENSE) file for details.
