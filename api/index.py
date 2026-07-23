"""Vercel entrypoint.

@vercel/python looks for a variable named `app` in this file. The real
FastAPI app and all its routes live in app/main.py unprefixed (e.g.
/water_transfer/recommend); mounting it at /api here - rather than editing
its route decorators - is what makes vercel.json's "/api/(.*)" routing rule
line up, while local `uvicorn app.main:app` runs still hit the same routes
unprefixed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI

from app.main import app as pump_chatbot_app

app = FastAPI()
app.mount("/api", pump_chatbot_app)
