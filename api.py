"""Root ASGI entry point for the Taxi Grouper API."""

from src.api.launcher import get_api_host
from src.api.service import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=get_api_host(), port=8000)
