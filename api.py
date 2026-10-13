"""Root ASGI entry point for the Taxi Grouper API."""

import os

from src.api.service import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.getenv("API_HOST") or "127.0.0.1", port=8000)
