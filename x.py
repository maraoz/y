#!/usr/bin/env python3

import sys
import os
import json
import argparse
import requests
import curses
from datetime import datetime
from requests_oauthlib import OAuth1
from typing import Optional, Dict, Any, List

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
        error_msg = f"HTTP {r.status_code}: {json.dumps(body, ensure_ascii=False)}"
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

def create_tweet(text: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
    """Post a tweet, optionally as a reply."""
    payload = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}
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

# ============================================================================
# TUI COMPONENTS
# ============================================================================

def render_tweet_list(stdscr, tweets: List[Dict[str, Any]], current_idx: int, header: str = "Tweets"):
    """Render a list of tweets (generic for mentions or own tweets)."""
    stdscr.clear()
    height, width = stdscr.getmaxyx()

    # Header
    stdscr.addstr(0, 0, f"{header} (↑/↓ to navigate, ENTER to reply, q to quit)", curses.A_BOLD)
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

def get_reply_input(stdscr, tweet: Dict[str, Any], action_label: str = "Replying to") -> Optional[str]:
    """Show reply composition screen and get user input."""
    curses.echo()
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
            if y_offset < height - 5:
                stdscr.addstr(y_offset, 0, current_line.strip())
                y_offset += 1
            current_line = word + " "
    if current_line and y_offset < height - 5:
        stdscr.addstr(y_offset, 0, current_line.strip())
        y_offset += 1

    y_offset += 1
    stdscr.addstr(y_offset, 0, "─" * min(width - 1, 80))
    y_offset += 1
    stdscr.addstr(y_offset, 0, "Your reply (ENTER to send, ESC to cancel):")
    y_offset += 1

    stdscr.refresh()

    # Get input
    reply_input = ""
    cursor_pos = 0

    while True:
        try:
            stdscr.move(y_offset, cursor_pos)
            stdscr.clrtoeol()
            stdscr.addstr(y_offset, 0, reply_input)
            stdscr.move(y_offset, cursor_pos)
        except curses.error:
            pass

        stdscr.refresh()
        ch = stdscr.getch()

        if ch == 27:  # ESC
            curses.noecho()
            curses.curs_set(0)
            return None
        elif ch == ord('\n'):  # ENTER
            curses.noecho()
            curses.curs_set(0)
            return reply_input.strip()
        elif ch == curses.KEY_BACKSPACE or ch == 127 or ch == 8:
            if cursor_pos > 0:
                reply_input = reply_input[:cursor_pos-1] + reply_input[cursor_pos:]
                cursor_pos -= 1
        elif ch == curses.KEY_LEFT:
            if cursor_pos > 0:
                cursor_pos -= 1
        elif ch == curses.KEY_RIGHT:
            if cursor_pos < len(reply_input):
                cursor_pos += 1
        elif 32 <= ch <= 126:  # Printable characters
            reply_input = reply_input[:cursor_pos] + chr(ch) + reply_input[cursor_pos:]
            cursor_pos += 1

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

def cmd_post(text: str):
    """CLI command: post a tweet."""
    resp = create_tweet(text)
    data = resp.get("data", {})
    print(json.dumps({"id": data.get("id"), "text": data.get("text")}, ensure_ascii=False))

def cmd_mentions(show_all: bool, limit: int):
    """CLI command: list mentions."""
    me = get_authenticated_user()["data"]
    mentions = fetch_mentions(only_unread=(not show_all), max_results=limit)
    print(json.dumps({"user": me, "mentions": mentions}, ensure_ascii=False, indent=2))

def cmd_engagements(limit: int):
    """CLI command: show engagement metrics."""
    me = get_authenticated_user()["data"]
    tweets = fetch_user_tweets(limit=limit)
    print(json.dumps({"user": me, "tweets": tweets}, ensure_ascii=False, indent=2))

def cmd_interact(limit: int):
    """CLI command: interactive mention browser."""
    print("Fetching mentions...")
    mentions = fetch_mentions(only_unread=False, max_results=limit)

    if not mentions:
        print("No mentions found.")
        return

    curses.wrapper(interactive_tweet_controller, mentions, "Mentions", "Replying to")

def cmd_thread(limit: int):
    """CLI command: interactive thread builder for own tweets."""
    print("Fetching your tweets...")
    tweets = fetch_user_tweets(limit=limit, include_author=True)

    if not tweets:
        print("No tweets found.")
        return

    curses.wrapper(interactive_tweet_controller, tweets, "Your Tweets", "Threading")

# ============================================================================
# MAIN
# ============================================================================

def main(argv=None):
    parser = argparse.ArgumentParser(prog="x.py", description="Minimal X API v2 CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_post = sub.add_parser("post", help="Post a tweet")
    p_post.add_argument("text", help="Tweet text (wrap in quotes)")

    p_mentions = sub.add_parser("mentions", help="List mentions (@you), optionally unread since last run")
    p_mentions.add_argument("--all", action="store_true", help="Show recent mentions regardless of unread state")
    p_mentions.add_argument("--limit", type=int, default=20, help="Max results (5-100)")

    p_eng = sub.add_parser("engagements", help="Show public metrics for your recent tweets")
    p_eng.add_argument("--limit", type=int, default=10, help="How many recent tweets to fetch (5-100)")

    p_interact = sub.add_parser("interact", help="Interactive UI to browse and reply to mentions")
    p_interact.add_argument("--limit", type=int, default=5, help="How many recent mentions to fetch (5-100)")

    p_thread = sub.add_parser("thread", help="Interactive UI to build threads from your own tweets")
    p_thread.add_argument("--limit", type=int, default=10, help="How many recent tweets to fetch (5-100)")

    args = parser.parse_args(argv)

    try:
        if args.cmd == "post":
            cmd_post(args.text)
        elif args.cmd == "mentions":
            cmd_mentions(args.all, args.limit)
        elif args.cmd == "engagements":
            cmd_engagements(args.limit)
        elif args.cmd == "interact":
            cmd_interact(args.limit)
        elif args.cmd == "thread":
            cmd_thread(args.limit)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
