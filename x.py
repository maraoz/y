#!/usr/bin/env python3

import sys
import os
import json
import argparse
import requests
import curses
import subprocess
import tempfile
from datetime import datetime
from requests_oauthlib import OAuth1
from typing import Optional, Dict, Any, List, Tuple

from config import X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

# ============================================================================
# CONFIGURATION
# ============================================================================

X_API_BASE = "https://api.x.com"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".x_cli_state.json")

# ============================================================================
# API CLIENT LAYER
# ============================================================================

def client() -> OAuth1:
    """Create OAuth1 client for X API authentication."""
    return OAuth1(
        client_key=X_API_KEY,
        client_secret=X_API_SECRET,
        resource_owner_key=X_ACCESS_TOKEN,
        resource_owner_secret=X_ACCESS_TOKEN_SECRET,
    )

def api_request(method: str, path: str, params: Optional[Dict[str, Any]] = None,
                payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Generic API request handler with error handling."""
    url = f"{X_API_BASE.rstrip('/')}{path}"

    if method == "GET":
        r = requests.get(url, auth=client(), params=params, timeout=20)
    elif method == "POST":
        r = requests.post(url, auth=client(), json=payload, timeout=20)
    else:
        raise ValueError(f"Unsupported HTTP method: {method}")

    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}

        # Build detailed error message with request context
        error_lines = [f"API Error: {method} {path}"]

        # Add parameters if present
        if params:
            error_lines.append(f"Params: {json.dumps(params, ensure_ascii=False)}")
        if payload:
            error_lines.append(f"Payload: {json.dumps(payload, ensure_ascii=False)}")

        # Add response details
        error_lines.append(f"Status: {r.status_code}")

        # Parse error body for common fields
        if isinstance(body, dict):
            if "title" in body:
                error_lines.append(f"Error: {body['title']}")
            if "detail" in body:
                error_lines.append(f"Detail: {body['detail']}")
            if "type" in body:
                error_lines.append(f"Type: {body['type']}")
            # If there are other fields, show them too
            other_fields = {k: v for k, v in body.items() if k not in ["title", "detail", "type"]}
            if other_fields:
                error_lines.append(f"Additional info: {json.dumps(other_fields, ensure_ascii=False)}")
        else:
            error_lines.append(f"Response: {json.dumps(body, ensure_ascii=False)}")

        error_msg = "\n".join(error_lines)
        raise Exception(error_msg)

    return r.json()

# ============================================================================
# STATE MANAGEMENT
# ============================================================================

def load_state() -> Dict[str, Any]:
    """Load persistent state from disk."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state: Dict[str, Any]) -> None:
    """Save persistent state to disk."""
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write(f"Warning: could not write state file: {e}\n")

# ============================================================================
# API OPERATIONS
# ============================================================================

def get_authenticated_user() -> Dict[str, Any]:
    """Get the authenticated user's information."""
    return api_request("GET", "/2/users/me", params={"user.fields": "username"})

def create_tweet(text: str, reply_to_id: Optional[str] = None, media_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """Post a tweet, optionally as a reply and/or with media attachments."""
    payload = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    return api_request("POST", "/2/tweets", payload=payload)

def fetch_mentions(only_unread: bool = False, max_results: int = 20) -> List[Dict[str, Any]]:
    """Fetch mentions for the authenticated user."""
    me = get_authenticated_user()["data"]
    uid = me["id"]
    state = load_state()
    since_id = state.get("mentions_since_id") if only_unread else None

    params = {
        "max_results": max(5, min(max_results, 100)),
        "expansions": "author_id,in_reply_to_user_id,referenced_tweets.id",
        "tweet.fields": "created_at,conversation_id,in_reply_to_user_id,public_metrics,referenced_tweets",
        "user.fields": "username,name",
    }
    if since_id:
        params["since_id"] = since_id

    resp = api_request("GET", f"/2/users/{uid}/mentions", params=params)

    # Update state with newest mention ID
    data = resp.get("data", [])
    if data:
        newest_id = data[0]["id"]
        state["mentions_since_id"] = newest_id
        save_state(state)

    # Resolve author information
    users_index = {u["id"]: u for u in resp.get("includes", {}).get("users", [])}
    mentions = []
    for tweet in data:
        author = users_index.get(tweet.get("author_id"), {})
        mentions.append({
            "id": tweet["id"],
            "at": tweet.get("created_at"),
            "from": {
                "id": author.get("id"),
                "username": author.get("username"),
                "name": author.get("name")
            },
            "text": tweet.get("text"),
            "metrics": tweet.get("public_metrics", {}),
            "in_reply_to_user_id": tweet.get("in_reply_to_user_id"),
            "conversation_id": tweet.get("conversation_id"),
        })

    return mentions

def fetch_user_tweets(limit: int = 10, include_author: bool = False) -> List[Dict[str, Any]]:
    """Fetch recent tweets from the authenticated user."""
    me = get_authenticated_user()["data"]
    uid = me["id"]

    params = {
        "max_results": max(5, min(limit, 100)),
        "tweet.fields": "created_at,public_metrics",
    }

    resp = api_request("GET", f"/2/users/{uid}/tweets", params=params)
    tweets = resp.get("data", [])

    result = []
    for t in tweets:
        tweet_data = {
            "id": t["id"],
            "at": t.get("created_at"),
            "text": t.get("text"),
            "metrics": t.get("public_metrics", {}),
        }
        # Add author info if needed (for TUI compatibility)
        if include_author:
            tweet_data["from"] = {
                "id": me["id"],
                "username": me.get("username"),
                "name": me.get("name"),
            }
        result.append(tweet_data)

    return result

def fetch_timeline(limit: int = 10) -> List[Dict[str, Any]]:
    """Fetch recent tweets from users the authenticated user follows."""
    me = get_authenticated_user()["data"]
    uid = me["id"]

    params = {
        "max_results": max(5, min(limit, 100)),
        "expansions": "author_id",
        "tweet.fields": "created_at,public_metrics",
        "user.fields": "username,name",
    }

    resp = api_request("GET", f"/2/users/{uid}/timelines/reverse_chronological", params=params)

    data = resp.get("data", [])
    users_index = {u["id"]: u for u in resp.get("includes", {}).get("users", [])}

    tweets = []
    for t in data:
        author = users_index.get(t.get("author_id"), {})
        tweets.append({
            "id": t["id"],
            "at": t.get("created_at"),
            "from": {
                "id": author.get("id"),
                "username": author.get("username"),
                "name": author.get("name"),
            },
            "text": t.get("text"),
            "metrics": t.get("public_metrics", {}),
        })

    return tweets

# ============================================================================
# UTILITIES
# ============================================================================

def format_timestamp(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable format."""
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return iso_str

def grab_clipboard_image() -> Optional[str]:
    """
    Grab image from clipboard and save to temp file.
    Returns temp file path or None if failed.
    Currently supports macOS via pngpaste.
    """
    try:
        # Check if pngpaste is available (macOS)
        result = subprocess.run(['which', 'pngpaste'], capture_output=True, text=True)
        if result.returncode != 0:
            return None

        # Create temp file
        temp_fd, temp_path = tempfile.mkstemp(suffix='.png')
        os.close(temp_fd)

        # Run pngpaste to save clipboard to temp file
        result = subprocess.run(['pngpaste', temp_path], capture_output=True)
        if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            return temp_path
        else:
            # Clean up if failed
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            return None
    except Exception:
        return None

def upload_media(image_path: str) -> Optional[str]:
    """
    Upload media to X API and return media_id.
    Uses the v1.1 media/upload endpoint.
    """
    try:
        url = "https://upload.twitter.com/1.1/media/upload.json"

        with open(image_path, 'rb') as f:
            files = {'media': f}
            r = requests.post(url, auth=client(), files=files, timeout=60)

        if r.status_code >= 400:
            raise Exception(f"Media upload failed: HTTP {r.status_code}")

        data = r.json()
        return data.get('media_id_string')
    except Exception as e:
        raise Exception(f"Media upload error: {e}")

def image_to_ascii(image_path: str, width: int = 40) -> List[str]:
    """
    Convert image to ASCII art.
    Returns list of ASCII art lines.
    """
    try:
        from PIL import Image

        # ASCII characters from dark to light
        ascii_chars = " .:-=+*#%@"

        # Open and resize image
        img = Image.open(image_path)
        aspect_ratio = img.height / img.width
        height = int(width * aspect_ratio * 0.5)  # 0.5 to account for character aspect ratio
        img = img.resize((width, height))

        # Convert to grayscale
        img = img.convert('L')

        # Convert to ASCII
        pixels = list(img.getdata())
        ascii_art = []
        for i in range(0, len(pixels), width):
            row = pixels[i:i+width]
            ascii_line = ''.join([ascii_chars[min(int(pixel * len(ascii_chars) / 256), len(ascii_chars)-1)] for pixel in row])
            ascii_art.append(ascii_line)

        return ascii_art
    except ImportError:
        # PIL not available
        return ["[Image preview unavailable - install Pillow: pip install Pillow]"]
    except Exception as e:
        return [f"[Image preview error: {e}]"]

# ============================================================================
# TUI COMPONENTS
# ============================================================================

def render_tweet_list(stdscr, tweets: List[Dict[str, Any]], current_idx: int, header: str = "Tweets", show_detail_hint: bool = False):
    """Render a list of tweets (generic for mentions or own tweets)."""
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Header
    hint = "ENTER to view details" if show_detail_hint else "ENTER to reply"
    stdscr.addstr(0, 0, f"{header} (↑/↓ to navigate, {hint}, q to quit)", curses.A_BOLD)
    stdscr.addstr(1, 0, "─" * min(width - 1, 80))

    # Tweet list
    start_line = 2
    for i, tweet in enumerate(tweets):
        if start_line + i >= height - 1:
            break

        author = tweet.get("from", {})
        username = author.get("username", "unknown")
        timestamp = format_timestamp(tweet.get("at", ""))
        text = tweet.get("text", "")

        prefix = "> " if i == current_idx else "  "
        line = f"{prefix}@{username} [{timestamp}]: {text}"

        if len(line) > width - 1:
            line = line[:width - 4] + "..."

        attr = curses.A_REVERSE if i == current_idx else curses.A_NORMAL
        try:
            stdscr.addstr(start_line + i, 0, line, attr)
        except curses.error:
            pass

    stdscr.refresh()

def get_text_input(stdscr, prompt: str = "Enter text:") -> Optional[Tuple[str, Optional[List[str]]]]:
    """
    Get multiline text input from user in TUI with optional image attachment.
    Returns tuple of (text, media_ids) or None if cancelled.
    """
    curses.noecho()
    curses.curs_set(1)

    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Input area starts at line 4
    lines = [""]
    cursor_line = 0
    cursor_col = 0
    start_y = 4

    # Image attachment state (supports up to 4 images)
    attached_image_paths = []
    attached_media_ids = []

    def render_text():
        stdscr.clear()

        # Header
        stdscr.addstr(0, 0, prompt, curses.A_BOLD)
        stdscr.addstr(1, 0, "─" * min(width - 1, 80))
        stdscr.addstr(2, 0, "(Ctrl+V for image, ENTER for newline, Ctrl+D to submit, ESC to cancel)")
        # Blank line for spacing
        stdscr.addstr(3, 0, "")

        # Image indicator
        if attached_media_ids:
            count = len(attached_media_ids)
            text = f"📷 {count} image{'s' if count > 1 else ''} attached"
            stdscr.addstr(4, 0, text, curses.A_BOLD | curses.color_pair(0))

        # Calculate start position for text input
        text_start_y = start_y + 2  # Space for instructions and image indicator

        # Clear text input area
        for i in range(text_start_y, height - 1):
            stdscr.move(i, 0)
            stdscr.clrtoeol()

        # Render text lines
        for i, line in enumerate(lines):
            if text_start_y + i >= height - 1:
                break
            try:
                stdscr.addstr(text_start_y + i, 0, line[:width-1])
            except curses.error:
                pass

        # Position cursor
        try:
            stdscr.move(text_start_y + cursor_line, cursor_col)
        except curses.error:
            pass
        stdscr.refresh()

    while True:
        render_text()
        ch = stdscr.getch()

        if ch == 27:  # ESC
            curses.curs_set(0)
            # Clean up temp images
            for path in attached_image_paths:
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                    except:
                        pass
            return None
        elif ch == 4:  # Ctrl+D - submit
            curses.curs_set(0)
            # Clean up temp images
            for path in attached_image_paths:
                if os.path.exists(path):
                    try:
                        os.unlink(path)
                    except:
                        pass
            media_ids = attached_media_ids if attached_media_ids else None
            return ('\n'.join(lines), media_ids)
        elif ch == ord('\n') or ch == 10:  # ENTER or Ctrl+J - newline
            current_line = lines[cursor_line]
            lines[cursor_line] = current_line[:cursor_col]
            lines.insert(cursor_line + 1, current_line[cursor_col:])
            cursor_line += 1
            cursor_col = 0
        elif ch == 22:  # Ctrl+V - attach image from clipboard
            curses.curs_set(0)
            stdscr.clear()

            # Check if we've hit the limit
            if len(attached_media_ids) >= 4:
                stdscr.addstr(0, 0, "✗ Maximum 4 images allowed", curses.A_BOLD)
                stdscr.addstr(2, 0, "Press any key to continue...")
                stdscr.refresh()
                stdscr.getch()
                curses.curs_set(1)
            else:
                stdscr.addstr(0, 0, "Grabbing image from clipboard...", curses.A_BOLD)
                stdscr.refresh()

                # Grab image from clipboard
                image_path = grab_clipboard_image()
                if image_path:
                    stdscr.addstr(1, 0, "Uploading image...")
                    stdscr.refresh()

                    try:
                        # Upload to X API
                        media_id = upload_media(image_path)
                        if media_id:
                            attached_media_ids.append(media_id)
                            attached_image_paths.append(image_path)
                            count = len(attached_media_ids)
                            stdscr.addstr(2, 0, f"✓ Image {count} attached successfully!", curses.A_BOLD)
                        else:
                            stdscr.addstr(2, 0, "✗ Failed to upload image", curses.A_BOLD)
                            if os.path.exists(image_path):
                                os.unlink(image_path)
                    except Exception as e:
                        stdscr.addstr(2, 0, f"✗ Error: {str(e)[:width-10]}", curses.A_BOLD)
                        if os.path.exists(image_path):
                            os.unlink(image_path)
                else:
                    stdscr.addstr(1, 0, "✗ No image found in clipboard", curses.A_BOLD)
                    stdscr.addstr(2, 0, "(Make sure 'pngpaste' is installed: brew install pngpaste)")

                stdscr.addstr(3, 0, "Press any key to continue...")
                stdscr.refresh()
                stdscr.getch()
                curses.curs_set(1)
        elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            if cursor_col > 0:
                current_line = lines[cursor_line]
                lines[cursor_line] = current_line[:cursor_col-1] + current_line[cursor_col:]
                cursor_col -= 1
            elif cursor_line > 0:
                # Join with previous line
                prev_line = lines[cursor_line - 1]
                cursor_col = len(prev_line)
                lines[cursor_line - 1] = prev_line + lines[cursor_line]
                lines.pop(cursor_line)
                cursor_line -= 1
        elif ch == curses.KEY_UP:
            if cursor_line > 0:
                cursor_line -= 1
                cursor_col = min(cursor_col, len(lines[cursor_line]))
        elif ch == curses.KEY_DOWN:
            if cursor_line < len(lines) - 1:
                cursor_line += 1
                cursor_col = min(cursor_col, len(lines[cursor_line]))
        elif ch == curses.KEY_LEFT:
            if cursor_col > 0:
                cursor_col -= 1
            elif cursor_line > 0:
                cursor_line -= 1
                cursor_col = len(lines[cursor_line])
        elif ch == curses.KEY_RIGHT:
            if cursor_col < len(lines[cursor_line]):
                cursor_col += 1
            elif cursor_line < len(lines) - 1:
                cursor_line += 1
                cursor_col = 0
        elif 32 <= ch <= 126:  # Printable characters
            current_line = lines[cursor_line]
            lines[cursor_line] = current_line[:cursor_col] + chr(ch) + current_line[cursor_col:]
            cursor_col += 1

def get_reply_input(stdscr, tweet: Dict[str, Any], action_label: str = "Replying to") -> Optional[str]:
    """Show reply composition screen and get multiline user input."""
    curses.noecho()
    curses.curs_set(1)

    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Display tweet being replied to
    author = tweet.get("from", {})
    username = author.get("username", "unknown")
    timestamp = format_timestamp(tweet.get("at", ""))
    text = tweet.get("text", "")

    stdscr.addstr(0, 0, f"{action_label}:", curses.A_BOLD)
    stdscr.addstr(1, 0, f"@{username} [{timestamp}]")
    stdscr.addstr(2, 0, "─" * min(width - 1, 80))

    # Word-wrap tweet text
    y_offset = 3
    words = text.split()
    current_line = ""
    for word in words:
        if len(current_line) + len(word) + 1 <= width - 1:
            current_line += word + " "
        else:
            if y_offset < height - 8:
                stdscr.addstr(y_offset, 0, current_line.strip())
                y_offset += 1
            current_line = word + " "
    if current_line and y_offset < height - 8:
        stdscr.addstr(y_offset, 0, current_line.strip())
        y_offset += 1

    y_offset += 1
    stdscr.addstr(y_offset, 0, "─" * min(width - 1, 80))
    y_offset += 1
    stdscr.addstr(y_offset, 0, "Your reply (ENTER for newline, Ctrl+D to send, ESC to cancel):")
    y_offset += 1

    start_y = y_offset
    stdscr.refresh()

    # Input handling with multiline support
    lines = [""]
    cursor_line = 0
    cursor_col = 0

    def render_input():
        # Clear input area
        for i in range(start_y, height - 1):
            stdscr.move(i, 0)
            stdscr.clrtoeol()

        # Render lines
        for i, line in enumerate(lines):
            if start_y + i >= height - 1:
                break
            try:
                stdscr.addstr(start_y + i, 0, line[:width-1])
            except curses.error:
                pass

        # Position cursor
        try:
            stdscr.move(start_y + cursor_line, cursor_col)
        except curses.error:
            pass
        stdscr.refresh()

    while True:
        render_input()
        ch = stdscr.getch()

        if ch == 27:  # ESC
            curses.curs_set(0)
            return None
        elif ch == 4:  # Ctrl+D - submit
            curses.curs_set(0)
            return '\n'.join(lines)
        elif ch == ord('\n') or ch == 10:  # ENTER or Ctrl+J - newline
            current_line = lines[cursor_line]
            lines[cursor_line] = current_line[:cursor_col]
            lines.insert(cursor_line + 1, current_line[cursor_col:])
            cursor_line += 1
            cursor_col = 0
        elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            if cursor_col > 0:
                current_line = lines[cursor_line]
                lines[cursor_line] = current_line[:cursor_col-1] + current_line[cursor_col:]
                cursor_col -= 1
            elif cursor_line > 0:
                # Join with previous line
                prev_line = lines[cursor_line - 1]
                cursor_col = len(prev_line)
                lines[cursor_line - 1] = prev_line + lines[cursor_line]
                lines.pop(cursor_line)
                cursor_line -= 1
        elif ch == curses.KEY_UP:
            if cursor_line > 0:
                cursor_line -= 1
                cursor_col = min(cursor_col, len(lines[cursor_line]))
        elif ch == curses.KEY_DOWN:
            if cursor_line < len(lines) - 1:
                cursor_line += 1
                cursor_col = min(cursor_col, len(lines[cursor_line]))
        elif ch == curses.KEY_LEFT:
            if cursor_col > 0:
                cursor_col -= 1
            elif cursor_line > 0:
                cursor_line -= 1
                cursor_col = len(lines[cursor_line])
        elif ch == curses.KEY_RIGHT:
            if cursor_col < len(lines[cursor_line]):
                cursor_col += 1
            elif cursor_line < len(lines) - 1:
                cursor_line += 1
                cursor_col = 0
        elif 32 <= ch <= 126:  # Printable characters
            current_line = lines[cursor_line]
            lines[cursor_line] = current_line[:cursor_col] + chr(ch) + current_line[cursor_col:]
            cursor_col += 1

def show_success_message(stdscr, message: str, tweet_id: str):
    """Display success message after sending a reply."""
    stdscr.clear()
    stdscr.addstr(0, 0, message, curses.A_BOLD)
    stdscr.addstr(1, 0, f"Tweet ID: {tweet_id}")
    stdscr.addstr(3, 0, "Press any key to exit...")
    stdscr.refresh()
    stdscr.getch()

def show_error_message(stdscr, error: str):
    """Display error message in TUI."""
    stdscr.clear()
    stdscr.addstr(0, 0, f"Error: {error}", curses.A_BOLD)
    stdscr.addstr(2, 0, "Press any key to continue...")
    stdscr.refresh()
    stdscr.getch()

# ============================================================================
# TUI CONTROLLER
# ============================================================================

def main_menu_controller(stdscr) -> Optional[str]:
    """Main menu TUI. Returns selected command or None."""
    curses.curs_set(0)
    stdscr.clear()

    commands = [
        ("interact", "Mentions"),
        ("thread", "Build threads"),
        ("timeline", "View timeline"),
        ("engagement", "View engagement metrics"),
        ("post", "Post a tweet"),
        ("quit", "Exit"),
    ]

    current_idx = 0

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Header
        stdscr.addstr(0, 0, "X CLI - Main Menu", curses.A_BOLD)
        stdscr.addstr(1, 0, "─" * min(width - 1, 80))
        stdscr.addstr(2, 0, "Use ↑/↓ to navigate, ENTER to select, q to quit")
        stdscr.addstr(3, 0, "")

        # Command list
        start_line = 4
        for i, (cmd, desc) in enumerate(commands):
            if start_line + i >= height - 1:
                break

            prefix = "> " if i == current_idx else "  "
            line = f"{prefix}{desc}"

            attr = curses.A_REVERSE if i == current_idx else curses.A_NORMAL
            try:
                stdscr.addstr(start_line + i, 0, line, attr)
            except curses.error:
                pass

        stdscr.refresh()

        # Handle input
        key = stdscr.getch()

        if key == curses.KEY_UP and current_idx > 0:
            current_idx -= 1
        elif key == curses.KEY_DOWN and current_idx < len(commands) - 1:
            current_idx += 1
        elif key == ord('q') or key == ord('Q'):
            return None
        elif key == ord('\n'):  # Enter
            selected_cmd = commands[current_idx][0]
            if selected_cmd == "quit":
                return None
            return selected_cmd

def browse_tweets_controller(stdscr, tweets: List[Dict[str, Any]], header: str = "Tweets"):
    """Read-only tweet browser with detailed view."""
    curses.curs_set(0)
    current_idx = 0
    detail_view = False

    while True:
        if detail_view:
            # Show detailed view of selected tweet
            stdscr.clear()
            height, width = stdscr.getmaxyx()

            tweet = tweets[current_idx]
            author = tweet.get("from", {})
            username = author.get("username", "unknown")
            timestamp = format_timestamp(tweet.get("at", ""))
            text = tweet.get("text", "")
            metrics = tweet.get("metrics", {})

            stdscr.addstr(0, 0, f"Tweet {current_idx + 1}/{len(tweets)}", curses.A_BOLD)
            stdscr.addstr(1, 0, "─" * min(width - 1, 80))
            stdscr.addstr(2, 0, f"@{username}")
            stdscr.addstr(3, 0, f"[{timestamp}]")
            stdscr.addstr(4, 0, "")

            # Word-wrap tweet text
            y_offset = 5
            words = text.split()
            current_line = ""
            for word in words:
                if len(current_line) + len(word) + 1 <= width - 1:
                    current_line += word + " "
                else:
                    if y_offset < height - 6:
                        stdscr.addstr(y_offset, 0, current_line.strip())
                        y_offset += 1
                    current_line = word + " "
            if current_line and y_offset < height - 6:
                stdscr.addstr(y_offset, 0, current_line.strip())
                y_offset += 1

            # Metrics
            y_offset += 1
            stdscr.addstr(y_offset, 0, "─" * min(width - 1, 80))
            y_offset += 1
            likes = metrics.get("like_count", 0)
            retweets = metrics.get("retweet_count", 0)
            replies = metrics.get("reply_count", 0)
            stdscr.addstr(y_offset, 0, f"❤️  {likes}  🔁 {retweets}  💬 {replies}")

            stdscr.addstr(height - 2, 0, "ESC: back to list, ↑/↓: navigate, q: quit", curses.A_DIM)
            stdscr.refresh()

            key = stdscr.getch()
            if key == 27:  # ESC
                detail_view = False
            elif key == curses.KEY_UP and current_idx > 0:
                current_idx -= 1
            elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
                current_idx += 1
            elif key == ord('q') or key == ord('Q'):
                break
        else:
            # Show list view
            render_tweet_list(stdscr, tweets, current_idx, header, show_detail_hint=True)
            key = stdscr.getch()

            if key == curses.KEY_UP and current_idx > 0:
                current_idx -= 1
            elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
                current_idx += 1
            elif key == ord('q') or key == ord('Q'):
                break
            elif key == ord('\n'):  # Enter - show detail
                detail_view = True

def interactive_tweet_controller(stdscr, tweets: List[Dict[str, Any]], header: str = "Tweets", action_label: str = "Replying to"):
    """Main controller for interactive tweet browsing TUI (works for mentions or own tweets)."""
    curses.curs_set(0)
    current_idx = 0

    while True:
        render_tweet_list(stdscr, tweets, current_idx, header)
        key = stdscr.getch()

        if key == curses.KEY_UP and current_idx > 0:
            current_idx -= 1
        elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
            current_idx += 1
        elif key == ord('q') or key == ord('Q'):
            break
        elif key == ord('\n'):  # Enter key
            selected = tweets[current_idx]
            reply_text = get_reply_input(stdscr, selected, action_label)

            if reply_text is not None:
                stdscr.clear()
                stdscr.addstr(0, 0, "Sending reply...")
                stdscr.refresh()

                try:
                    resp = create_tweet(reply_text, reply_to_id=selected["id"])
                    tweet_id = resp.get('data', {}).get('id', 'unknown')
                    show_success_message(stdscr, "Reply sent successfully!", tweet_id)
                    break
                except Exception as e:
                    show_error_message(stdscr, str(e))

# ============================================================================
# CLI COMMANDS
# ============================================================================

def cmd_post(text: Optional[str] = None):
    """CLI command: post a tweet."""
    if text is None:
        # Interactive mode - get text via TUI
        def post_tui(stdscr):
            result = get_text_input(stdscr, "Post a tweet")
            if result is None:
                return None

            tweet_text, media_ids = result

            stdscr.clear()
            stdscr.addstr(0, 0, "Posting tweet...")
            stdscr.refresh()

            try:
                resp = create_tweet(tweet_text, media_ids=media_ids)
                tweet_id = resp.get('data', {}).get('id', 'unknown')
                show_success_message(stdscr, "Tweet posted successfully!", tweet_id)
                return resp
            except Exception as e:
                show_error_message(stdscr, str(e))
                return None

        curses.wrapper(post_tui)
    else:
        # Direct command mode - use provided text
        resp = create_tweet(text)
        data = resp.get("data", {})
        print(json.dumps({"id": data.get("id"), "text": data.get("text")}, ensure_ascii=False))

def cmd_mentions(show_all: bool, limit: int):
    """CLI command: list mentions (interactive)."""
    def mentions_tui(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Fetching mentions...")
        stdscr.refresh()

        mentions = fetch_mentions(only_unread=(not show_all), max_results=limit)

        if not mentions:
            stdscr.clear()
            stdscr.addstr(0, 0, "No mentions found.")
            stdscr.addstr(2, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        browse_tweets_controller(stdscr, mentions, "Mentions")

    curses.wrapper(mentions_tui)

def cmd_engagement(limit: int):
    """CLI command: show engagement metrics (interactive)."""
    def engagement_tui(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Fetching your tweets...")
        stdscr.refresh()

        tweets = fetch_user_tweets(limit=limit, include_author=True)

        if not tweets:
            stdscr.clear()
            stdscr.addstr(0, 0, "No tweets found.")
            stdscr.addstr(2, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        browse_tweets_controller(stdscr, tweets, "Your Tweets - Engagement")

    curses.wrapper(engagement_tui)

def cmd_interact(limit: int):
    """CLI command: interactive mention browser."""
    def interact_tui(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Fetching mentions...")
        stdscr.refresh()

        mentions = fetch_mentions(only_unread=False, max_results=limit)

        if not mentions:
            stdscr.clear()
            stdscr.addstr(0, 0, "No mentions found.")
            stdscr.addstr(2, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        interactive_tweet_controller(stdscr, mentions, "Mentions", "Replying to")

    curses.wrapper(interact_tui)

def cmd_thread(limit: int):
    """CLI command: interactive thread builder for own tweets."""
    def thread_tui(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Fetching your tweets...")
        stdscr.refresh()

        tweets = fetch_user_tweets(limit=limit, include_author=True)

        if not tweets:
            stdscr.clear()
            stdscr.addstr(0, 0, "No tweets found.")
            stdscr.addstr(2, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        interactive_tweet_controller(stdscr, tweets, "Your Tweets", "Threading")

    curses.wrapper(thread_tui)

def cmd_timeline(limit: int):
    """CLI command: list recent tweets from timeline (interactive)."""
    def timeline_tui(stdscr):
        stdscr.clear()
        stdscr.addstr(0, 0, "Fetching timeline...")
        stdscr.refresh()

        tweets = fetch_timeline(limit=limit)

        if not tweets:
            stdscr.clear()
            stdscr.addstr(0, 0, "No tweets found.")
            stdscr.addstr(2, 0, "Press any key to exit...")
            stdscr.refresh()
            stdscr.getch()
            return

        browse_tweets_controller(stdscr, tweets, "Timeline")

    curses.wrapper(timeline_tui)

# ============================================================================
# MAIN
# ============================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(prog="x.py", description="Minimal X API v2 CLI")
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_post = sub.add_parser("post", help="Post a tweet")
    p_post.add_argument("text", nargs="?", help="Tweet text (optional, will prompt if not provided)")

    p_mentions = sub.add_parser("mentions", help="List mentions (@you), optionally unread since last run")
    p_mentions.add_argument("--all", action="store_true", help="Show recent mentions regardless of unread state")
    p_mentions.add_argument("--limit", type=int, default=5, help="Max results (5-100)")

    p_eng = sub.add_parser("engagement", help="Show engagement metrics for your recent tweets")
    p_eng.add_argument("--limit", type=int, default=5, help="How many recent tweets to fetch (5-100)")

    p_interact = sub.add_parser("interact", help="Browse and reply to mentions")
    p_interact.add_argument("--limit", type=int, default=5, help="How many recent mentions to fetch (5-100)")

    p_thread = sub.add_parser("thread", help="Build threads from your own tweets")
    p_thread.add_argument("--limit", type=int, default=5, help="How many recent tweets to fetch (5-100)")

    p_timeline = sub.add_parser("timeline", help="List recent tweets from your timeline")
    p_timeline.add_argument("--limit", type=int, default=5, help="How many recent tweets to fetch (5-100)")

    args = parser.parse_args(argv)

    try:
        # If no command specified, show main menu
        if args.cmd is None:
            selected = curses.wrapper(main_menu_controller)
            if selected is None:
                return

            # Execute selected command
            if selected == "post":
                cmd_post()
            elif selected == "engagement":
                cmd_engagement(limit=5)
            elif selected == "interact":
                cmd_interact(limit=5)
            elif selected == "thread":
                cmd_thread(limit=5)
            elif selected == "timeline":
                cmd_timeline(limit=5)
        else:
            # Direct command execution
            if args.cmd == "post":
                cmd_post(args.text)
            elif args.cmd == "mentions":
                cmd_mentions(args.all, args.limit)
            elif args.cmd == "engagement":
                cmd_engagement(args.limit)
            elif args.cmd == "interact":
                cmd_interact(args.limit)
            elif args.cmd == "thread":
                cmd_thread(args.limit)
            elif args.cmd == "timeline":
                cmd_timeline(args.limit)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
