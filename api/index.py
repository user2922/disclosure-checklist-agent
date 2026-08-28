"""Vercel serverless entry point.

Vercel's Python runtime serves the ASGI app exported here; vercel.json rewrites
every path to this function. Locally the app is still run directly with
`uvicorn app.main:app` — this file adds nothing but the entry point.
"""

from app.main import app

__all__ = ["app"]
