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
X_API_BASE = "https://api.x.com"

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".x_cli_state.json")

def client():
    return OAuth1(
        client_key=X_API_KEY,
        client_secret=X_API_SECRET,
        resource_owner_key=X_ACCESS_TOKEN,
        resource_owner_secret=X_ACCESS_TOKEN_SECRET,
    )

def api(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{X_API_BASE.rstrip('/')}{path}"
    r = requests.get(url, auth=client(), params=params, timeout=20)
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}
        sys.stderr.write(f"HTTP {r.status_code}: {json.dumps(body, ensure_ascii=False)}\n")
        sys.exit(1)
    return r.json()

def api_post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = f"{X_API_BASE.rstrip('/')}{path}"
    r = requests.post(url, auth=client(), json=payload, timeout=20)
    if r.status_code >= 400:
        try:
            body = r.json()
        except Exception:
            body = {"raw": r.text}
        sys.stderr.write(f"HTTP {r.status_code}: {json.dumps(body, ensure_ascii=False)}\n")
        sys.exit(1)
    return r.json()

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_state(s: Dict[str, Any]) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception as e:
        sys.stderr.write(f"Warning: could not write state file: {e}\n")

def get_me() -> Dict[str, Any]:
    # Returns {"data": {"id": "...", "name": "...", "username": "..." }}
    return api("/2/users/me", params={"user.fields": "username"})

def post_tweet(text: str, reply_to_id: Optional[str] = None) -> Dict[str, Any]:
    payload = {"text": text}
    if reply_to_id:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to_id}
    return api_post("/2/tweets", payload)

def list_mentions(only_unread: bool, max_results: int) -> Dict[str, Any]:
    me = get_me()["data"]
    uid = me["id"]
    state = load_state()
    since_id = state.get("mentions_since_id") if only_unread else None

    params = {
        "max_results": max(5, min(max_results, 100)),
        # expansions to get context
        "expansions": "author_id,in_reply_to_user_id,referenced_tweets.id",
        "tweet.fields": "created_at,conversation_id,in_reply_to_user_id,public_metrics,referenced_tweets",
        "user.fields": "username,name",
    }
    if since_id:
        params["since_id"] = since_id

    resp = api(f"/2/users/{uid}/mentions", params=params)

    # Update state with newest mention id so next run can be "unread"
    data = resp.get("data", [])
    if data:
        newest_id = data[0]["id"]
        state["mentions_since_id"] = newest_id
        save_state(state)

    # Compact output: resolve author usernames
    users_index = {u["id"]: u for u in resp.get("includes", {}).get("users", [])}
    out: List[Dict[str, Any]] = []
    for t in data:
        author = users_index.get(t.get("author_id"), {})
        out.append({
            "id": t["id"],
            "at": t.get("created_at"),
            "from": {"id": author.get("id"), "username": author.get("username"), "name": author.get("name")},
            "text": t.get("text"),
            "metrics": t.get("public_metrics", {}),
            "in_reply_to_user_id": t.get("in_reply_to_user_id"),
            "conversation_id": t.get("conversation_id"),
        })
    return {"user": me, "mentions": out}

def list_engagements(limit: int) -> Dict[str, Any]:
    me = get_me()["data"]
    uid = me["id"]
    # Pull your recent tweets with public metrics
    params = {
        "max_results": max(5, min(limit, 100)),
        "tweet.fields": "created_at,public_metrics",
        # We want originals + replies; exclude retweets is optional. Keep all for signal.
        # "exclude": "retweets"  # uncomment to suppress RTs you posted
    }
    resp = api(f"/2/users/{uid}/tweets", params=params)
    tweets = resp.get("data", [])
    compact = [{
        "id": t["id"],
        "at": t.get("created_at"),
        "text": t.get("text"),
        "metrics": t.get("public_metrics", {}),
    } for t in tweets]
    return {"user": me, "tweets": compact}

def format_timestamp(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable format"""
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return dt.strftime("%b %d, %Y %I:%M %p")
    except Exception:
        return iso_str

def interactive_mentions(stdscr, limit: int):
    """Interactive TUI for browsing and replying to mentions"""
    curses.curs_set(0)  # Hide cursor
    stdscr.clear()

    # Fetch mentions
    stdscr.addstr(0, 0, "Fetching mentions...")
    stdscr.refresh()

    resp = list_mentions(only_unread=False, max_results=limit)
    mentions = resp.get("mentions", [])

    if not mentions:
        stdscr.clear()
        stdscr.addstr(0, 0, "No mentions found. Press any key to exit.")
        stdscr.refresh()
        stdscr.getch()
        return

    current_idx = 0

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Display header
        stdscr.addstr(0, 0, "Mentions (↑/↓ to navigate, ENTER to reply, q to quit)", curses.A_BOLD)
        stdscr.addstr(1, 0, "─" * min(width - 1, 80))

        # Display mentions
        start_line = 2
        for i, mention in enumerate(mentions):
            if start_line + i >= height - 1:
                break

            author = mention.get("from", {})
            username = author.get("username", "unknown")
            timestamp = format_timestamp(mention.get("at", ""))
            text = mention.get("text", "")

            prefix = "> " if i == current_idx else "  "
            line = f"{prefix}@{username} [{timestamp}]: {text}"

            # Truncate if too long
            if len(line) > width - 1:
                line = line[:width - 4] + "..."

            attr = curses.A_REVERSE if i == current_idx else curses.A_NORMAL
            try:
                stdscr.addstr(start_line + i, 0, line, attr)
            except curses.error:
                pass  # Ignore errors from writing to last line

        stdscr.refresh()

        # Handle input
        key = stdscr.getch()

        if key == curses.KEY_UP and current_idx > 0:
            current_idx -= 1
        elif key == curses.KEY_DOWN and current_idx < len(mentions) - 1:
            current_idx += 1
        elif key == ord('q') or key == ord('Q'):
            break
        elif key == ord('\n'):  # Enter key
            # Show reply interface
            selected = mentions[current_idx]
            reply_text = show_reply_screen(stdscr, selected)

            if reply_text is not None:  # None means ESC was pressed
                # Send the reply
                stdscr.clear()
                stdscr.addstr(0, 0, "Sending reply...")
                stdscr.refresh()

                try:
                    resp = post_tweet(reply_text, reply_to_id=selected["id"])
                    stdscr.clear()
                    stdscr.addstr(0, 0, "Reply sent successfully!", curses.A_BOLD)
                    stdscr.addstr(1, 0, f"Tweet ID: {resp.get('data', {}).get('id', 'unknown')}")
                    stdscr.addstr(3, 0, "Press any key to exit...")
                    stdscr.refresh()
                    stdscr.getch()
                    break
                except Exception as e:
                    stdscr.clear()
                    stdscr.addstr(0, 0, f"Error sending reply: {str(e)}", curses.A_BOLD)
                    stdscr.addstr(2, 0, "Press any key to continue...")
                    stdscr.refresh()
                    stdscr.getch()

def show_reply_screen(stdscr, mention: Dict[str, Any]) -> Optional[str]:
    """Show reply composition screen. Returns reply text or None if ESC pressed."""
    curses.echo()
    curses.curs_set(1)

    while True:
        stdscr.clear()
        height, width = stdscr.getmaxyx()

        # Display the tweet being replied to
        author = mention.get("from", {})
        username = author.get("username", "unknown")
        timestamp = format_timestamp(mention.get("at", ""))
        text = mention.get("text", "")

        stdscr.addstr(0, 0, "Replying to:", curses.A_BOLD)
        stdscr.addstr(1, 0, f"@{username} [{timestamp}]")
        stdscr.addstr(2, 0, "─" * min(width - 1, 80))

        # Display tweet text (word-wrapped)
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

        # Get reply input
        curses.curs_set(1)
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

    args = parser.parse_args(argv)

    if args.cmd == "post":
        resp = post_tweet(args.text)
        data = resp.get("data", {})
        print(json.dumps({"id": data.get("id"), "text": data.get("text")}, ensure_ascii=False))
    elif args.cmd == "mentions":
        resp = list_mentions(only_unread=(not args.all), max_results=args.limit)
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    elif args.cmd == "engagements":
        resp = list_engagements(limit=args.limit)
        print(json.dumps(resp, ensure_ascii=False, indent=2))
    elif args.cmd == "interact":
        curses.wrapper(interactive_mentions, args.limit)

if __name__ == "__main__":
    main()

