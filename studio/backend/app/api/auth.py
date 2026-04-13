"""
Mark II Studio — GitHub OAuth Routes
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, HTTPException

from app.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/logout")
async def logout():
    """Invalidate the current session (client-side token drop)."""
    return {"detail": "Logged out successfully"}


@router.get("/github")
async def github_login():
    """Redirect user to GitHub OAuth authorization page."""
    if not settings.github_client_id:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={settings.github_client_id}"
        f"&redirect_uri={settings.github_redirect_uri}"
        f"&scope=read:user,repo"
    )
    return {"redirect_url": url}


@router.get("/github/callback")
async def github_callback(code: str):
    """Exchange authorization code for access token and create/login user."""
    if not settings.github_client_id or not settings.github_client_secret:
        raise HTTPException(status_code=501, detail="GitHub OAuth not configured")

    # Exchange code for token
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            json={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )
        token_data = token_response.json()
        access_token = token_data.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="GitHub OAuth failed")

        # Fetch user profile
        user_response = await client.get(
            "https://api.github.com/user",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_data = user_response.json()

    return {
        "github_id": user_data.get("id"),
        "github_login": user_data.get("login"),
        "avatar_url": user_data.get("avatar_url", ""),
        "access_token": access_token,
    }
