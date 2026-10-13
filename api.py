"""Root ASGI entry point for the Taxi Grouper API."""

from src.api.service import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
