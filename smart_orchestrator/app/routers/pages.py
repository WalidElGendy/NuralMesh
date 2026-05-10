from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

WEB_DIR = Path(__file__).resolve().parents[3] / "web"
router = APIRouter(tags=["web"])


def _html(name: str) -> FileResponse:
    path = WEB_DIR / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Page not found")
    return FileResponse(path)


@router.get("/")
@router.get("/index.html")
async def index():
    return _html("index.html")


@router.get("/signup.html")
async def signup():
    return _html("signup.html")


@router.get("/login.html")
async def login():
    return _html("login.html")


@router.get("/account.html")
async def account():
    return _html("account.html")


@router.get("/chat")
async def chat_page():
    return _html("chat.html")


@router.get("/host/setup")
async def host_setup():
    return _html("host/setup.html")


@router.get("/host/terms.html")
async def host_terms():
    return _html("host/terms.html")

