"""Shared authentication helpers for manual API test/debug scripts."""

import os


def api_auth_headers() -> dict[str, str]:
    api_key = os.getenv("TAXI_GROUPER_API_KEY")
    if not api_key:
        raise RuntimeError("Set TAXI_GROUPER_API_KEY in the environment before calling protected API routes.")
    return {"Authorization": f"Bearer {api_key}"}
