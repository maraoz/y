# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

X (Twitter) API v2 CLI tool. Single Python file with commands for posting tweets, viewing mentions, and checking engagement metrics. Includes interactive TUI for replying to mentions.

## Configuration

Requires OAuth 1.0a credentials in `config.py`:
```python
X_API_KEY = "..."
X_API_SECRET = "..."
X_ACCESS_TOKEN = "..."
X_ACCESS_TOKEN_SECRET = "..."
```

**Never commit `config.py` to version control.**

## Commands

**Interactive menu:**
```bash
./x.py                               # Main menu with arrow key navigation
```

**Direct commands (all interactive TUI):**
```bash
./x.py post [text]                   # Post tweet (prompts in TUI if text not provided)
./x.py mentions [--all] [--limit N]  # Browse mentions (read-only with detail view)
./x.py interact [--limit N]          # Browse mentions and reply
./x.py thread [--limit N]            # Browse your tweets and build threads
./x.py timeline [--limit N]          # Browse timeline (read-only with detail view)
./x.py engagement [--limit N]        # Browse your tweets with metrics (read-only)
```

**TUI Features:**
- List view with arrow key navigation
- Press ENTER for detail view (shows full tweet + metrics)
- ESC to go back from detail view
- Can navigate between tweets while in detail view

## Code Structure

**Clean layer separation:**
- **API Client Layer** (lines 22-55): `api_request()` handles all HTTP
- **State Management** (lines 57-77): `.x_cli_state.json` for unread tracking
- **API Operations** (lines 79-158): Business logic, returns clean data
- **TUI Components** (lines 172-305): Curses rendering and input
- **TUI Controller** (lines 307-341): Coordinates UI flow
- **CLI Commands** (lines 343-374): Entry points, fetch data before entering curses
- **Main** (lines 376-416): Arg parsing and error handling

**Key pattern:** API calls happen outside curses mode to ensure errors print to terminal.

## Dependencies

- `requests`, `requests_oauthlib` for API
- `curses` for TUI (stdlib)
