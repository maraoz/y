#!/usr/bin/env python3

import sys
import os
import json
import argparse
import requests
import subprocess
import tempfile
from datetime import datetime
from requests_oauthlib import OAuth1
from typing import Optional, Dict, Any, List, Tuple

os.environ.setdefault('ESCDELAY', '100')
import curses

from config import X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET

# Key codes
KEY_ESC = 27
KEY_CTRL_D = 4
KEY_CTRL_V = 22
KEY_NEWLINE = 10
KEY_BACKSPACE_1 = 127
KEY_BACKSPACE_2 = 8
KEY_PRINTABLE_START = 32
KEY_PRINTABLE_END = 126

# Config
X_API_BASE = "https://api.x.com"
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".x_cli_state.json")
MAX_IMAGES = 4

# Common UI strings
MSG_LOADING = "loading⋯"
MSG_NOTHING = "nothing here"
MSG_PRESS_KEY = "press any key"
MSG_SENDING = "sending⋯"

# ============================================================================
# API
# ============================================================================

def client() -> OAuth1:
    return OAuth1(
        client_key=X_API_KEY,
        client_secret=X_API_SECRET,
        resource_owner_key=X_ACCESS_TOKEN,
        resource_owner_secret=X_ACCESS_TOKEN_SECRET,
    )

def api_request(method: str, path: str, params: Optional[Dict[str, Any]] = None,
                payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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

        error_lines = [f"API Error: {method} {path}"]
        if params:
            error_lines.append(f"Params: {json.dumps(params, ensure_ascii=False)}")
        if payload:
            error_lines.append(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
        error_lines.append(f"Status: {r.status_code}")

        if isinstance(body, dict):
            if "title" in body:
                error_lines.append(f"Error: {body['title']}")
            if "detail" in body:
                error_lines.append(f"Detail: {body['detail']}")
            if "type" in body:
                error_lines.append(f"Type: {body['type']}")
            other_fields = {k: v for k, v in body.items() if k not in ["title", "detail", "type"]}
            if other_fields:
                error_lines.append(f"Additional info: {json.dumps(other_fields, ensure_ascii=False)}")
        else:
            error_lines.append(f"Response: {json.dumps(body, ensure_ascii=False)}")

        raise Exception("\n".join(error_lines))

    return r.json()

# ============================================================================
# State
# ============================================================================

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(state: Dict[str, Any]) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write(f"Warning: could not write state file: {e}\n")

# ============================================================================
# X API Operations
# ============================================================================

def get_authenticated_user() -> Dict[str, Any]:
    return api_request("GET", "/2/users/me", params={"user.fields": "username"})

def get_cached_user() -> Dict[str, Any]:
    state = load_state()
    if "user_cache" in state:
        return state["user_cache"]

    user_data = get_authenticated_user()
    state["user_cache"] = user_data
    save_state(state)
    return user_data

def create_tweet(text: str, reply_to_id: Optional[str] = None, media_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    payload = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}
    if media_ids:
        payload["media"] = {"media_ids": media_ids}
    return api_request("POST", "/2/tweets", payload=payload)

def fetch_mentions(only_unread: bool = False, max_results: int = 20) -> List[Dict[str, Any]]:
    me = get_cached_user()["data"]
    state = load_state()

    params = {
        "max_results": max(5, min(max_results, 100)),
        "expansions": "author_id,in_reply_to_user_id,referenced_tweets.id",
        "tweet.fields": "created_at,conversation_id,in_reply_to_user_id,public_metrics,referenced_tweets",
        "user.fields": "username,name",
    }
    if only_unread and "mentions_since_id" in state:
        params["since_id"] = state["mentions_since_id"]

    resp = api_request("GET", f"/2/users/{me['id']}/mentions", params=params)
    data = resp.get("data", [])

    if data:
        state["mentions_since_id"] = data[0]["id"]
        save_state(state)

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

def get_cached_tweets() -> List[Dict[str, Any]]:
    """Get cached tweets from local state."""
    state = load_state()
    return state.get("tweets_cache", [])

def add_tweet_to_cache(tweet_id: str, tweet_text: str) -> None:
    """Add newly posted tweet to cache (prepends to list)."""
    me = get_cached_user()["data"]
    state = load_state()
    cache = state.get("tweets_cache", [])

    new_tweet = {
        "id": tweet_id,
        "at": datetime.now().isoformat() + "Z",
        "text": tweet_text,
        "metrics": {"retweet_count": 0, "reply_count": 0, "like_count": 0, "quote_count": 0},
        "from": {
            "id": me["id"],
            "username": me.get("username"),
            "name": me.get("name"),
        }
    }

    # Prepend new tweet and keep max 100 cached tweets
    cache.insert(0, new_tweet)
    state["tweets_cache"] = cache[:100]
    save_state(state)

def fetch_user_tweets(limit: int = 10, include_author: bool = False) -> List[Dict[str, Any]]:
    me = get_cached_user()["data"]
    params = {
        "max_results": max(5, min(limit, 100)),
        "tweet.fields": "created_at,public_metrics",
    }

    resp = api_request("GET", f"/2/users/{me['id']}/tweets", params=params)
    tweets = resp.get("data", [])

    result = []
    for t in tweets:
        tweet_data = {
            "id": t["id"],
            "at": t.get("created_at"),
            "text": t.get("text"),
            "metrics": t.get("public_metrics", {}),
        }
        if include_author:
            tweet_data["from"] = {
                "id": me["id"],
                "username": me.get("username"),
                "name": me.get("name"),
            }
        result.append(tweet_data)

    # Cache tweets for offline access (useful for threading when API is down)
    if result:
        state = load_state()
        state["tweets_cache"] = result
        save_state(state)

    return result

def fetch_timeline(limit: int = 10) -> List[Dict[str, Any]]:
    me = get_cached_user()["data"]
    params = {
        "max_results": max(5, min(limit, 100)),
        "expansions": "author_id",
        "tweet.fields": "created_at,public_metrics",
        "user.fields": "username,name",
    }

    resp = api_request("GET", f"/2/users/{me['id']}/timelines/reverse_chronological", params=params)
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
# Utilities
# ============================================================================

def format_timestamp(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return iso_str

def word_wrap(text: str, width: int) -> List[str]:
    """Word-wrap text to fit within width. Returns list of lines."""
    lines = []
    for paragraph in text.split('\n'):
        words = paragraph.split()
        current_line = ""
        for word in words:
            if len(current_line) + len(word) + 1 <= width:
                current_line += word + " "
            else:
                if current_line:
                    lines.append(current_line.strip())
                current_line = word + " "
        if current_line:
            lines.append(current_line.strip())
    return lines

def cleanup_temp_files(paths: List[str]) -> None:
    """Remove temporary files."""
    for path in paths:
        if os.path.exists(path):
            try:
                os.unlink(path)
            except Exception:
                pass

def grab_clipboard_image() -> Optional[str]:
    """Grab image from clipboard via pngpaste (macOS). Returns temp file path."""
    try:
        result = subprocess.run(['which', 'pngpaste'], capture_output=True, text=True)
        if result.returncode != 0:
            return None

        temp_fd, temp_path = tempfile.mkstemp(suffix='.png')
        os.close(temp_fd)

        result = subprocess.run(['pngpaste', temp_path], capture_output=True)
        if result.returncode == 0 and os.path.exists(temp_path) and os.path.getsize(temp_path) > 0:
            return temp_path

        if os.path.exists(temp_path):
            os.unlink(temp_path)
        return None
    except Exception:
        return None

def upload_media(image_path: str) -> Optional[str]:
    """Upload media to X API. Returns media_id_string."""
    try:
        with open(image_path, 'rb') as f:
            r = requests.post("https://upload.twitter.com/1.1/media/upload.json",
                            auth=client(), files={'media': f}, timeout=60)

        if r.status_code >= 400:
            raise Exception(f"Media upload failed: HTTP {r.status_code}")

        return r.json().get('media_id_string')
    except Exception as e:
        raise Exception(f"Media upload error: {e}")

# ============================================================================
# TUI Helpers
# ============================================================================

def is_real_escape(stdscr) -> bool:
    """Distinguish real ESC from escape sequences (like Option+arrow)."""
    stdscr.nodelay(True)
    try:
        return stdscr.getch() == -1
    finally:
        stdscr.nodelay(False)

def show_empty_state(stdscr, message: str = MSG_NOTHING):
    """Show empty state message."""
    stdscr.clear()
    stdscr.addstr(0, 0, message, curses.A_DIM)
    stdscr.addstr(2, 0, MSG_PRESS_KEY, curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()

# ============================================================================
# TUI Components
# ============================================================================

def render_tweet_list(stdscr, tweets: List[Dict[str, Any]], current_idx: int, header: str = "tweets", show_detail_hint: bool = False):
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    hint = "enter view" if show_detail_hint else "enter reply"
    stdscr.addstr(0, 0, header, curses.A_BOLD)
    stdscr.addstr(1, 0, f"↑↓ navigate · {hint} · esc back", curses.A_DIM)

    start_line = 2
    for i, tweet in enumerate(tweets):
        if start_line + i >= height - 1:
            break

        author = tweet.get("from", {})
        username = author.get("username", "unknown")
        timestamp = format_timestamp(tweet.get("at", ""))
        text = tweet.get("text", "")

        prefix = "▸ " if i == current_idx else "  "
        line = f"{prefix}@{username} · {timestamp} · {text}"

        if len(line) > width - 1:
            line = line[:width - 4] + "⋯"

        attr = curses.A_REVERSE if i == current_idx else curses.A_NORMAL
        try:
            stdscr.addstr(start_line + i, 0, line, attr)
        except curses.error:
            pass

    stdscr.refresh()

def get_multiline_input(stdscr, header_lines: List[str],
                       context_tweet: Optional[Dict[str, Any]] = None,
                       help_text: str = "ctrl+v image · enter newline · ctrl+d send · esc cancel") -> Optional[Tuple[str, Optional[List[str]]]]:
    """Get multiline text input with optional image attachments.

    If context_tweet is provided, displays it before the input area.
    Returns (text, media_ids) or None if cancelled.
    """
    curses.noecho()
    curses.curs_set(1)

    height, width = stdscr.getmaxyx()
    lines = [""]
    cursor_line = 0
    cursor_col = 0
    attached_image_paths = []
    attached_media_ids = []

    def render():
        stdscr.clear()
        y = 0

        for i, line in enumerate(header_lines):
            attr = curses.A_BOLD if i == 0 else (curses.A_DIM if line else curses.A_NORMAL)
            try:
                stdscr.addstr(y, 0, line, attr)
            except curses.error:
                pass
            y += 1

        if context_tweet:
            author = context_tweet.get("from", {})
            username = author.get("username", "unknown")
            timestamp = format_timestamp(context_tweet.get("at", ""))
            stdscr.addstr(y, 0, f"@{username} · {timestamp}", curses.A_DIM)
            y += 1
            stdscr.addstr(y, 0, "")
            y += 1

            wrapped = word_wrap(context_tweet.get("text", ""), width - 1)
            for line in wrapped[:min(len(wrapped), height - y - 10)]:
                stdscr.addstr(y, 0, line)
                y += 1
            y += 1

        stdscr.addstr(y, 0, help_text, curses.A_DIM)
        y += 1

        if attached_media_ids:
            count = len(attached_media_ids)
            stdscr.addstr(y, 0, f"📷 {count}" if count > 1 else "📷", curses.A_DIM)
            y += 1

        text_start_y = y
        for i in range(text_start_y, height - 1):
            stdscr.move(i, 0)
            stdscr.clrtoeol()

        for i, line in enumerate(lines):
            if text_start_y + i >= height - 1:
                break
            try:
                stdscr.addstr(text_start_y + i, 0, line[:width-1])
            except curses.error:
                pass

        try:
            stdscr.move(text_start_y + cursor_line, cursor_col)
        except curses.error:
            pass
        stdscr.refresh()

    def handle_image_attach():
        curses.curs_set(0)
        stdscr.clear()

        if len(attached_media_ids) >= MAX_IMAGES:
            stdscr.addstr(0, 0, f"✗ max {MAX_IMAGES} images", curses.A_BOLD)
            stdscr.addstr(2, 0, MSG_PRESS_KEY, curses.A_DIM)
            stdscr.refresh()
            stdscr.getch()
            curses.curs_set(1)
            return

        stdscr.addstr(0, 0, "grabbing image⋯", curses.A_DIM)
        stdscr.refresh()

        image_path = grab_clipboard_image()
        if image_path:
            stdscr.addstr(1, 0, "uploading⋯", curses.A_DIM)
            stdscr.refresh()

            try:
                media_id = upload_media(image_path)
                if media_id:
                    attached_media_ids.append(media_id)
                    attached_image_paths.append(image_path)
                    stdscr.addstr(2, 0, f"✓ image {len(attached_media_ids)} attached", curses.A_BOLD)
                else:
                    stdscr.addstr(2, 0, "✗ upload failed", curses.A_BOLD)
                    if os.path.exists(image_path):
                        os.unlink(image_path)
            except Exception as e:
                stdscr.addstr(2, 0, f"✗ Error: {str(e)[:width-10]}", curses.A_BOLD)
                if os.path.exists(image_path):
                    os.unlink(image_path)
        else:
            stdscr.addstr(1, 0, "✗ no image in clipboard", curses.A_BOLD)
            stdscr.addstr(2, 0, "install pngpaste: brew install pngpaste", curses.A_DIM)

        stdscr.addstr(3, 0, MSG_PRESS_KEY, curses.A_DIM)
        stdscr.refresh()
        stdscr.getch()
        curses.curs_set(1)

    while True:
        render()
        ch = stdscr.getch()

        if ch == KEY_ESC and is_real_escape(stdscr):
            curses.curs_set(0)
            cleanup_temp_files(attached_image_paths)
            return None
        elif ch == KEY_CTRL_D:
            curses.curs_set(0)
            cleanup_temp_files(attached_image_paths)
            return ('\n'.join(lines), attached_media_ids if attached_media_ids else None)
        elif ch == ord('\n') or ch == KEY_NEWLINE:
            current_line = lines[cursor_line]
            lines[cursor_line] = current_line[:cursor_col]
            lines.insert(cursor_line + 1, current_line[cursor_col:])
            cursor_line += 1
            cursor_col = 0
        elif ch == KEY_CTRL_V:
            handle_image_attach()
        elif ch == curses.KEY_BACKSPACE or ch == KEY_BACKSPACE_1 or ch == KEY_BACKSPACE_2:
            if cursor_col > 0:
                current_line = lines[cursor_line]
                lines[cursor_line] = current_line[:cursor_col-1] + current_line[cursor_col:]
                cursor_col -= 1
            elif cursor_line > 0:
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
        elif KEY_PRINTABLE_START <= ch <= KEY_PRINTABLE_END:
            current_line = lines[cursor_line]
            lines[cursor_line] = current_line[:cursor_col] + chr(ch) + current_line[cursor_col:]
            cursor_col += 1

def get_text_input(stdscr, prompt: str = "write") -> Optional[Tuple[str, Optional[List[str]]]]:
    return get_multiline_input(stdscr, [prompt])

def get_reply_input(stdscr, tweet: Dict[str, Any], action_label: str = "replying to") -> Optional[Tuple[str, Optional[List[str]]]]:
    return get_multiline_input(stdscr, [action_label, ""], context_tweet=tweet)

def show_success_message(stdscr, message: str, tweet_url: str):
    stdscr.clear()
    stdscr.addstr(0, 0, "✓", curses.A_BOLD)
    stdscr.addstr(1, 0, message, curses.A_DIM)
    stdscr.addstr(2, 0, "")
    stdscr.addstr(3, 0, tweet_url, curses.A_DIM)
    stdscr.addstr(5, 0, MSG_PRESS_KEY, curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()

def show_error_message(stdscr, error: str):
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    stdscr.addstr(0, 0, "error", curses.A_BOLD)
    stdscr.addstr(1, 0, "")

    y_offset = 2
    for wrapped_line in word_wrap(error, width - 1):
        if y_offset < height - 4:
            stdscr.addstr(y_offset, 0, wrapped_line)
            y_offset += 1

    stdscr.addstr(height - 2, 0, "press any key to continue", curses.A_DIM)
    stdscr.refresh()
    stdscr.getch()

def render_tweet_detail(stdscr, tweet: Dict[str, Any], current_idx: int, total_tweets: int, hint: str):
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    author = tweet.get("from", {})
    username = author.get("username", "unknown")
    timestamp = format_timestamp(tweet.get("at", ""))
    metrics = tweet.get("metrics", {})

    stdscr.addstr(0, 0, f"{current_idx + 1}/{total_tweets}", curses.A_BOLD)
    stdscr.addstr(1, 0, f"@{username} · {timestamp}", curses.A_DIM)
    stdscr.addstr(2, 0, "")

    y_offset = 5
    for wrapped_line in word_wrap(tweet.get("text", ""), width - 1):
        if y_offset < height - 6:
            stdscr.addstr(y_offset, 0, wrapped_line)
            y_offset += 1

    y_offset += 1
    likes = metrics.get("like_count", 0)
    retweets = metrics.get("retweet_count", 0)
    replies = metrics.get("reply_count", 0)
    stdscr.addstr(y_offset, 0, f"❤️ {likes}  🔁 {retweets}  💬 {replies}", curses.A_DIM)

    stdscr.addstr(height - 2, 0, hint, curses.A_DIM)
    stdscr.refresh()

# ============================================================================
# Controllers
# ============================================================================

def main_menu_controller(stdscr) -> Optional[str]:
    curses.curs_set(0)
    commands = [
        ("post", "write"),
        ("interact", "mentions"),
        ("engagement", "ego"),
        ("timeline", "catchup"),
        ("quit", "exit"),
    ]
    current_idx = 0

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        stdscr.addstr(0, 0, "×", curses.A_BOLD)
        stdscr.addstr(2, 0, "↑↓ navigate · enter select · esc quit", curses.A_DIM)

        start_line = 4
        for i, (cmd, desc) in enumerate(commands):
            if start_line + i >= height - 1:
                break
            prefix = "▸ " if i == current_idx else "  "
            attr = curses.A_REVERSE if i == current_idx else curses.A_NORMAL
            try:
                stdscr.addstr(start_line + i, 0, f"{prefix}{desc}", attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP and current_idx > 0:
            current_idx -= 1
        elif key == curses.KEY_DOWN and current_idx < len(commands) - 1:
            current_idx += 1
        elif key == ord('q') or key == ord('Q') or key == KEY_ESC:
            return None
        elif key == ord('\n'):
            selected_cmd = commands[current_idx][0]
            return None if selected_cmd == "quit" else selected_cmd

def browse_tweets_controller(stdscr, tweets: List[Dict[str, Any]], header: str = "tweets"):
    curses.curs_set(0)
    current_idx = 0
    detail_view = False

    while True:
        if detail_view:
            render_tweet_detail(stdscr, tweets[current_idx], current_idx, len(tweets), "↑↓ navigate · esc back")
            key = stdscr.getch()
            if key == KEY_ESC:
                detail_view = False
            elif key == curses.KEY_UP and current_idx > 0:
                current_idx -= 1
            elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
                current_idx += 1
            elif key == ord('q') or key == ord('Q') or key == KEY_ESC:
                break
        else:
            render_tweet_list(stdscr, tweets, current_idx, header, show_detail_hint=True)
            key = stdscr.getch()

            if key == curses.KEY_UP and current_idx > 0:
                current_idx -= 1
            elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
                current_idx += 1
            elif key == ord('q') or key == ord('Q') or key == KEY_ESC:
                break
            elif key == ord('\n'):
                detail_view = True

def interactive_tweet_controller(stdscr, tweets: List[Dict[str, Any]], header: str = "tweets", action_label: str = "replying to"):
    curses.curs_set(0)
    current_idx = 0
    detail_view = False

    while True:
        if detail_view:
            render_tweet_detail(stdscr, tweets[current_idx], current_idx, len(tweets), "↑↓ navigate · enter reply · esc back")
            key = stdscr.getch()
            if key == KEY_ESC:
                detail_view = False
            elif key == curses.KEY_UP and current_idx > 0:
                current_idx -= 1
            elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
                current_idx += 1
            elif key == ord('q') or key == ord('Q'):
                break
            elif key == ord('\n'):
                selected = tweets[current_idx]
                result = get_reply_input(stdscr, selected, action_label)

                if result:
                    reply_text, media_ids = result
                    stdscr.clear()
                    stdscr.addstr(0, 0, MSG_SENDING)
                    stdscr.refresh()

                    try:
                        resp = create_tweet(reply_text, reply_to_id=selected["id"], media_ids=media_ids)
                        me = get_cached_user()["data"]
                        tweet_id = resp.get('data', {}).get('id', 'unknown')
                        tweet_url = f"https://x.com/{me.get('username', 'unknown')}/status/{tweet_id}"
                        add_tweet_to_cache(tweet_id, reply_text)
                        show_success_message(stdscr, "reply sent", tweet_url)
                        break
                    except Exception as e:
                        show_error_message(stdscr, str(e))
        else:
            render_tweet_list(stdscr, tweets, current_idx, header, show_detail_hint=True)
            key = stdscr.getch()

            if key == curses.KEY_UP and current_idx > 0:
                current_idx -= 1
            elif key == curses.KEY_DOWN and current_idx < len(tweets) - 1:
                current_idx += 1
            elif key == ord('q') or key == ord('Q') or key == KEY_ESC:
                break
            elif key == ord('\n'):
                detail_view = True

def write_menu_controller(stdscr):
    curses.curs_set(0)
    items = [{"type": "new", "text": "new"}]
    current_idx = 0

    try:
        stdscr.clear()
        stdscr.addstr(0, 0, "write", curses.A_BOLD)
        stdscr.addstr(1, 0, "↑↓ navigate · enter select · esc back", curses.A_DIM)
        stdscr.addstr(3, 0, "▸ new", curses.A_REVERSE)
        stdscr.addstr(4, 0, f"  {MSG_LOADING}", curses.A_DIM)
        stdscr.refresh()

        tweets = fetch_user_tweets(limit=5, include_author=True)
        for tweet in tweets:
            items.append({"type": "tweet", "data": tweet})
    except Exception:
        # Try cached tweets as fallback
        cached = get_cached_tweets()
        if cached:
            for tweet in cached[:5]:
                items.append({"type": "tweet", "data": tweet})
            items.append({"type": "error", "text": "(using cached tweets)"})
        else:
            items.append({"type": "error", "text": "(failed to fetch previous posts)"})

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        stdscr.addstr(0, 0, "write", curses.A_BOLD)
        stdscr.addstr(1, 0, "↑↓ navigate · enter select · esc back", curses.A_DIM)

        start_line = 3
        for i, item in enumerate(items):
            if start_line + i >= height - 1:
                break

            prefix = "▸ " if i == current_idx else "  "

            if item["type"] == "new":
                line = f"{prefix}new"
            elif item["type"] == "error":
                line = f"{prefix}{item['text']}"
            else:
                text = item["data"].get("text", "")
                if len(text) > 50:
                    text = text[:47] + "⋯"
                line = f"{prefix}{text}"

            if len(line) > width - 1:
                line = line[:width - 4] + "⋯"

            attr = curses.A_REVERSE if i == current_idx else curses.A_NORMAL
            try:
                stdscr.addstr(start_line + i, 0, line, attr)
            except curses.error:
                pass

        stdscr.refresh()
        key = stdscr.getch()

        if key == curses.KEY_UP and current_idx > 0:
            current_idx -= 1
        elif key == curses.KEY_DOWN and current_idx < len(items) - 1:
            current_idx += 1
        elif key == ord('q') or key == ord('Q') or key == KEY_ESC:
            return
        elif key == ord('\n'):
            selected = items[current_idx]
            if selected["type"] == "error":
                continue

            if selected["type"] == "new":
                result = get_text_input(stdscr, "write")
                if not result:
                    continue

                tweet_text, media_ids = result
                stdscr.clear()
                stdscr.addstr(0, 0, MSG_SENDING, curses.A_DIM)
                stdscr.refresh()

                try:
                    resp = create_tweet(tweet_text, media_ids=media_ids)
                    me = get_cached_user()["data"]
                    tweet_id = resp.get('data', {}).get('id', 'unknown')
                    tweet_url = f"https://x.com/{me.get('username', 'unknown')}/status/{tweet_id}"
                    add_tweet_to_cache(tweet_id, tweet_text)
                    show_success_message(stdscr, "posted", tweet_url)
                    return
                except Exception as e:
                    show_error_message(stdscr, str(e))
            else:
                tweet = selected["data"]
                result = get_reply_input(stdscr, tweet, "continue")
                if not result:
                    continue

                reply_text, media_ids = result
                stdscr.clear()
                stdscr.addstr(0, 0, MSG_SENDING)
                stdscr.refresh()

                try:
                    resp = create_tweet(reply_text, reply_to_id=tweet["id"], media_ids=media_ids)
                    me = get_cached_user()["data"]
                    tweet_id = resp.get('data', {}).get('id', 'unknown')
                    tweet_url = f"https://x.com/{me.get('username', 'unknown')}/status/{tweet_id}"
                    add_tweet_to_cache(tweet_id, reply_text)
                    show_success_message(stdscr, "thread posted", tweet_url)
                    return
                except Exception as e:
                    show_error_message(stdscr, str(e))

# ============================================================================
# CLI Commands
# ============================================================================

def cmd_post(text: Optional[str] = None, stdscr=None):
    if text is None:
        if stdscr:
            write_menu_controller(stdscr)
        else:
            curses.wrapper(write_menu_controller)
    else:
        resp = create_tweet(text)
        data = resp.get("data", {})
        tweet_id = data.get("id")
        add_tweet_to_cache(tweet_id, text)
        print(json.dumps({"id": tweet_id, "text": data.get("text")}, ensure_ascii=False))

def cmd_mentions(show_all: bool, limit: int, stdscr=None):
    def mentions_tui(scr):
        scr.clear()
        scr.addstr(0, 0, MSG_LOADING, curses.A_DIM)
        scr.refresh()

        try:
            mentions = fetch_mentions(only_unread=(not show_all), max_results=limit)
        except Exception as e:
            show_error_message(scr, str(e))
            return

        if not mentions:
            show_empty_state(scr)
            return

        browse_tweets_controller(scr, mentions, "mentions")

    if stdscr:
        mentions_tui(stdscr)
    else:
        curses.wrapper(mentions_tui)

def cmd_engagement(limit: int, stdscr=None):
    def engagement_tui(scr):
        scr.clear()
        scr.addstr(0, 0, MSG_LOADING, curses.A_DIM)
        scr.refresh()

        try:
            tweets = fetch_user_tweets(limit=limit, include_author=True)
        except Exception as e:
            show_error_message(scr, str(e))
            return

        if not tweets:
            show_empty_state(scr)
            return

        browse_tweets_controller(scr, tweets, "ego")

    if stdscr:
        engagement_tui(stdscr)
    else:
        curses.wrapper(engagement_tui)

def cmd_interact(limit: int, stdscr=None):
    def interact_tui(scr):
        scr.clear()
        scr.addstr(0, 0, MSG_LOADING, curses.A_DIM)
        scr.refresh()

        try:
            mentions = fetch_mentions(only_unread=False, max_results=limit)
        except Exception as e:
            show_error_message(scr, str(e))
            return

        if not mentions:
            show_empty_state(scr)
            return

        interactive_tweet_controller(scr, mentions, "mentions", "reply")

    if stdscr:
        interact_tui(stdscr)
    else:
        curses.wrapper(interact_tui)

def cmd_thread(limit: int, stdscr=None):
    def thread_tui(scr):
        scr.clear()
        scr.addstr(0, 0, MSG_LOADING, curses.A_DIM)
        scr.refresh()

        tweets = None
        using_cache = False

        try:
            tweets = fetch_user_tweets(limit=limit, include_author=True)
        except Exception as e:
            # Try cached tweets as fallback
            cached = get_cached_tweets()
            if cached:
                tweets = cached[:limit]
                using_cache = True
            else:
                show_error_message(scr, str(e))
                return

        if not tweets:
            show_empty_state(scr)
            return

        # If using cached data, show indicator in header
        header = "thread (cached)" if using_cache else "thread"
        interactive_tweet_controller(scr, tweets, header, "continue")

    if stdscr:
        thread_tui(stdscr)
    else:
        curses.wrapper(thread_tui)

def cmd_timeline(limit: int, stdscr=None):
    def timeline_tui(scr):
        scr.clear()
        scr.addstr(0, 0, MSG_LOADING, curses.A_DIM)
        scr.refresh()

        try:
            tweets = fetch_timeline(limit=limit)
        except Exception as e:
            show_error_message(scr, str(e))
            return

        if not tweets:
            show_empty_state(scr)
            return

        browse_tweets_controller(scr, tweets, "catchup")

    if stdscr:
        timeline_tui(stdscr)
    else:
        curses.wrapper(timeline_tui)

# ============================================================================
# Main
# ============================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(prog="x.py", description="X API v2 CLI")
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_post = sub.add_parser("post", help="Post a tweet")
    p_post.add_argument("text", nargs="?", help="Tweet text")

    p_mentions = sub.add_parser("mentions", help="List mentions")
    p_mentions.add_argument("--all", action="store_true", help="Show all mentions")
    p_mentions.add_argument("--limit", type=int, default=5, help="Max results (5-100)")

    p_eng = sub.add_parser("engagement", help="Show engagement metrics")
    p_eng.add_argument("--limit", type=int, default=5, help="Max results (5-100)")

    p_interact = sub.add_parser("interact", help="Browse and reply to mentions")
    p_interact.add_argument("--limit", type=int, default=5, help="Max results (5-100)")

    p_thread = sub.add_parser("thread", help="Build threads")
    p_thread.add_argument("--limit", type=int, default=5, help="Max results (5-100)")

    p_timeline = sub.add_parser("timeline", help="View timeline")
    p_timeline.add_argument("--limit", type=int, default=5, help="Max results (5-100)")

    args = parser.parse_args(argv)

    COMMANDS = {
        "post": lambda: cmd_post(args.text),
        "mentions": lambda: cmd_mentions(args.all, args.limit),
        "engagement": lambda: cmd_engagement(args.limit),
        "interact": lambda: cmd_interact(args.limit),
        "thread": lambda: cmd_thread(args.limit),
        "timeline": lambda: cmd_timeline(args.limit),
    }

    try:
        if args.cmd:
            COMMANDS[args.cmd]()
        else:
            def menu_loop(stdscr):
                while True:
                    selected = main_menu_controller(stdscr)
                    if selected is None:
                        return

                    cmd_map = {
                        "post": lambda: cmd_post(stdscr=stdscr),
                        "interact": lambda: cmd_interact(limit=5, stdscr=stdscr),
                        "engagement": lambda: cmd_engagement(limit=5, stdscr=stdscr),
                        "timeline": lambda: cmd_timeline(limit=5, stdscr=stdscr),
                    }
                    cmd_map[selected]()

            curses.wrapper(menu_loop)
    except KeyboardInterrupt:
        print("\nInterrupted")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
