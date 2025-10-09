# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is a minimal X (Twitter) API v2 CLI tool written in Python. The single-file script (`x.py`) provides a command-line interface for:
- Posting tweets
- Viewing mentions (with unread tracking)
- Checking engagement metrics on recent tweets

## Configuration

**CRITICAL**: The script expects OAuth 1.0a credentials to be imported from `config.py`:
- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`

The `config.py` file is currently empty and must be populated by the user before the script can run. These credentials should NOT be committed to version control.

## Common Commands

```bash
# Post a tweet
./x.py post "Tweet text here"

# List mentions (unread only by default)
./x.py mentions

# List all recent mentions (ignore unread tracking)
./x.py mentions --all

# List mentions with custom limit (5-100)
./x.py mentions --limit 50

# View engagement metrics on your recent tweets
./x.py engagements

# View engagements with custom limit
./x.py engagements --limit 20
```

## Architecture

**Single-file design**: All functionality is in `x.py` (~165 lines).

**State management**: The script maintains state in `.x_cli_state.json` to track the most recent mention ID seen. This enables "unread" mention filtering across CLI invocations.

**API client pattern**:
- `client()`: Returns OAuth1 session object
- `api()`: Generic GET request handler with error handling
- `api_post()`: Generic POST request handler with error handling
- All API functions return parsed JSON responses

**Core functions**:
- `get_me()`: Fetch authenticated user info
- `post_tweet()`: Create a new tweet
- `list_mentions()`: Fetch mentions with optional unread filtering
- `list_engagements()`: Fetch recent tweets with public metrics

**API base URL**: Configurable via `X_API_BASE` constant (line 5). Can be switched between `api.x.com` and `api.twitter.com` if needed.

**Output format**: All commands output JSON to stdout. Errors are written to stderr with HTTP status codes.

## Development Notes

- The script uses X API v2 endpoints exclusively
- OAuth 1.0a authentication via `requests_oauthlib`
- No external dependencies beyond `requests` and `requests_oauthlib`
- Error handling: HTTP errors (4xx/5xx) cause immediate exit with status code 1
- State file is automatically created in the same directory as the script
