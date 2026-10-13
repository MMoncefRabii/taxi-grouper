"""Shared settings for direct API launchers."""

import os


def get_api_host() -> str:
    """Return the API bind host, defaulting to loopback."""
    return os.getenv("API_HOST") or "127.0.0.1"
