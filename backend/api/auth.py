"""
Authentication API endpoints.
Provides profile lookup and token verification against PostgreSQL.
"""
from __future__ import annotations
import logging
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional

from backend.core.firebase_auth import get_current_user, get_current_user_optional, verify_id_token, get_or_create_user
from backend.database.models import User
from backend.database.session import check_db_connection, get_db_session
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("nexus.auth")

router = APIRouter()


class VerifyTokenRequest(BaseModel):
    id_token: str


@router.get("/me")
async def get_me(user: Optional[User] = Depends(get_current_user_optional)):
    """Return the authenticated user profile, or guest status if unauthenticated."""
    db_connected = await check_db_connection()
    if user is None:
        return {
            "authenticated": False,
            "guest": True,
            "database_connected": db_connected,
            "user": None,
        }
    return {
        "authenticated": True,
        "guest": False,
        "database_connected": db_connected,
        "user": user.to_dict(),
    }


@router.post("/verify")
async def verify_token(
    payload: VerifyTokenRequest,
    session: Optional[AsyncSession] = Depends(get_db_session),
):
    """Verify frontend Firebase token and ensure PostgreSQL user record exists."""
    claims = await verify_id_token(payload.id_token)
    if session is not None:
        user = await get_or_create_user(session, claims)
        return {
            "valid": True,
            "user": user.to_dict(),
        }
    return {
        "valid": True,
        "user": {
            "id": None,
            "firebase_uid": claims["uid"],
            "email": claims.get("email"),
            "display_name": claims.get("name"),
            "profile_image_url": claims.get("picture"),
        },
        "database_connected": False,
    }


class SessionStoreRequest(BaseModel):
    id_token: str
    firebase_uid: str
    email: Optional[str] = None
    display_name: Optional[str] = None
    profile_image_url: Optional[str] = None


import json
import os

SESSION_DIR = os.path.join(os.path.expanduser("~"), ".nexus")
SESSION_FILE = os.path.join(SESSION_DIR, "desktop_session.json")


def _load_persisted_session() -> Optional[dict]:
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[Auth] Could not read persisted session: {e}")
    return None


def _save_persisted_session(session_data: Optional[dict]):
    try:
        os.makedirs(SESSION_DIR, exist_ok=True)
        if session_data is None:
            if os.path.exists(SESSION_FILE):
                os.remove(SESSION_FILE)
        else:
            with open(SESSION_FILE, "w", encoding="utf-8") as f:
                json.dump(session_data, f)
    except Exception as e:
        logger.warning(f"[Auth] Could not save persisted session: {e}")


_active_desktop_session: Optional[dict] = _load_persisted_session()


@router.post("/session")
async def save_session(
    payload: SessionStoreRequest,
    session: Optional[AsyncSession] = Depends(get_db_session),
):
    global _active_desktop_session
    claims = await verify_id_token(payload.id_token)
    if claims.get("uid") != payload.firebase_uid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Firebase token does not match the supplied account.",
        )

    user_dict = {
        "id": None,
        "firebase_uid": claims["uid"],
        "email": claims.get("email") or payload.email,
        "display_name": claims.get("name") or payload.display_name,
        "profile_image_url": claims.get("picture") or payload.profile_image_url,
    }

    if session is not None:
        try:
            db_user = await get_or_create_user(session, claims)
            user_dict = db_user.to_dict()
        except Exception as e:
            logger.warning(f"[Auth] Could not create DB user: {e}")

    _active_desktop_session = {
        "user": user_dict,
        "id_token": payload.id_token,
    }
    _save_persisted_session(_active_desktop_session)
    return {"status": "ok", "user": user_dict}


@router.get("/session")
async def get_session():
    global _active_desktop_session
    if _active_desktop_session is None:
        _active_desktop_session = _load_persisted_session()
    return {"session": _active_desktop_session}


@router.post("/logout")
async def clear_session():
    global _active_desktop_session
    _active_desktop_session = None
    _save_persisted_session(None)
    return {"status": "ok"}

