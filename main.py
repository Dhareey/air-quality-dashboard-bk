"""Entry point: run with `uvicorn main:app --reload` (app is re-exported from app.main)."""

from app.main import app

__all__ = ["app"]
