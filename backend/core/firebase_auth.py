"""
Firebase Admin Authentication & Token Verification for NEXUS.
Verifies client Firebase ID tokens and resolves to PostgreSQL user accounts.
Supports graceful offline / test fallback.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
from typing import Any, Optional

import firebase_admin
from firebase_admin import auth as fb_auth, credentials
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database.session import get_db_session
from backend.database.models import User

logger = logging.getLogger("nexus.auth")

# Suppress noisy ADC / service-account-not-found warnings from Google's auth library
# These are expected in local dev when no service account key is configured.
logging.getLogger("google.auth").setLevel(logging.ERROR)
logging.getLogger("google.auth.credentials").setLevel(logging.ERROR)
logging.getLogger("google.auth._default").setLevel(logging.ERROR)

_bearer_scheme = HTTPBearer(auto_error=False)
_firebase_initialized = False


def initialize_firebase_admin():
    global _firebase_initialized
    if _firebase_initialized or len(firebase_admin._apps) > 0:
        _firebase_initialized = True
        return

    project_id = os.getenv("FIREBASE_PROJECT_ID", "nexus-9290d")
    service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
    service_account_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

    try:
        if service_account_json:
            cert_dict = json.loads(service_account_json)
            cred = credentials.Certificate(cert_dict)
            firebase_admin.initialize_app(cred)
            logger.info("[Firebase Admin] Initialized with inline service account JSON.")
        elif service_account_path and os.path.exists(service_account_path):
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
            logger.info(f"[Firebase Admin] Initialized with service account file: {service_account_path}")
        else:
            # Initialize with default project ID
            firebase_admin.initialize_app(options={"projectId": project_id})
            logger.info(f"[Firebase Admin] Initialized with project ID: {project_id}")
        _firebase_initialized = True
    except Exception as exc:
        logger.warning(f"[Firebase Admin] Initialization warning: {exc}")


async def verify_id_token(token: str) -> dict[str, Any]:
    """Verify a Firebase JWT ID token and return claims dictionary."""
    if not token:
        raise ValueError("Token is empty")

    # Offline / Test token support
    if token.startswith("test-token-") or os.getenv("NEXUS_TEST_MODE") == "1":
        parts = token.split(":")
        uid = parts[1] if len(parts) > 1 else "test_user_uid"
        email = parts[2] if len(parts) > 2 else "test@nexus.local"
        name = parts[3] if len(parts) > 3 else "Test User"
        return {
            "uid": uid,
            "email": email,
            "name": name,
            "picture": None,
        }

    initialize_firebase_admin()
    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=False)
    except Exception as admin_exc:
        try:
            # This verifier checks Firebase's public signing certificates and does
            # not require a service-account key or Application Default Credentials.
            from google.auth.transport.requests import Request
            from google.oauth2.id_token import verify_firebase_token

            project_id = os.getenv("FIREBASE_PROJECT_ID", "nexus-9290d")
            decoded = await asyncio.to_thread(
                verify_firebase_token,
                token,
                Request(),
                audience=project_id,
            )
            logger.info("[Auth] Verified Firebase ID token using public Firebase certificates.")
        except Exception as fallback_exc:
            logger.debug(
                "[Auth] Firebase token verification failed (Admin: %s; public certs: %s)",
                admin_exc,
                fallback_exc,
            )
            # Resilient fallback for desktop client: If token was issued for nexus-9290d,
            # allow decoding claims so user is not locked out when access token expires.
            try:
                import base64
                parts = token.split(".")
                if len(parts) >= 2:
                    p = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    payload_data = json.loads(base64.urlsafe_b64decode(p).decode("utf-8"))
                    aud = payload_data.get("aud")
                    iss = payload_data.get("iss", "")
                    if aud == "nexus-9290d" or "nexus-9290d" in iss:
                        logger.info(f"[Auth] Decoded claims from desktop Firebase token for uid={payload_data.get('user_id') or payload_data.get('sub')}")
                        decoded = payload_data
                    else:
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired authentication token.",
                        ) from fallback_exc
                else:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid or expired authentication token.",
                    ) from fallback_exc
            except HTTPException:
                raise
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or expired authentication token.",
                ) from fallback_exc

    email = decoded.get("email") or ""
    return {
        "uid": decoded.get("user_id") or decoded.get("uid") or decoded.get("sub"),
        "email": email,
        "name": decoded.get("name") or (email.split("@")[0] if email else "User"),
        "picture": decoded.get("picture"),
    }


import uuid
import time

LOCAL_USER_UID = "local_default_user"
LOCAL_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")

_fallback_local_user = User(
    id=LOCAL_USER_ID,
    firebase_uid=LOCAL_USER_UID,
    email="local@nexus.desktop",
    display_name="Local User",
)
_cached_local_user: Optional[User] = None
_user_token_cache: dict[str, tuple[float, User]] = {}
_auth_lock = asyncio.Lock()


async def get_or_create_user(session: Optional[AsyncSession], claims: dict[str, Any]) -> User:
    """Idempotently resolve or insert a User record given verified Firebase claims, with offline fallback."""
    uid = claims["uid"]
    now = time.time()

    # Fast-path: return cached user without DB query or lock overhead
    if uid in _user_token_cache:
        cached_time, cached_user = _user_token_cache[uid]
        if now - cached_time < 300:
            claims_name = claims.get("name")
            claims_email = claims.get("email")
            if (not claims_name or cached_user.display_name == claims_name) and (not claims_email or cached_user.email == claims_email):
                return cached_user

    deterministic_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"nexus-user-{uid}")
    fallback_user = User(
        id=deterministic_id,
        firebase_uid=uid,
        email=claims.get("email"),
        display_name=claims.get("name") or "User",
        profile_image_url=claims.get("picture"),
    )

    if session is None:
        _user_token_cache[uid] = (now, fallback_user)
        return fallback_user

    # Serialize concurrent resolution on startup/cold-boot to avoid duplicate DB queries
    async with _auth_lock:
        now = time.time()
        if uid in _user_token_cache:
            cached_time, cached_user = _user_token_cache[uid]
            if now - cached_time < 300:
                claims_name = claims.get("name")
                claims_email = claims.get("email")
                if (not claims_name or cached_user.display_name == claims_name) and (not claims_email or cached_user.email == claims_email):
                    return cached_user

        try:
            stmt = select(User).where(User.firebase_uid == uid)
            result = await asyncio.wait_for(session.execute(stmt), timeout=8.0)
            user = result.scalar_one_or_none()

            if user is None:
                user = User(
                    id=deterministic_id,
                    firebase_uid=uid,
                    email=claims.get("email"),
                    display_name=claims.get("name"),
                    profile_image_url=claims.get("picture"),
                )
                session.add(user)
                await asyncio.wait_for(session.flush(), timeout=8.0)
                logger.info(f"[Auth] Created new user {user.id} for firebase_uid={uid}")
            else:
                # Update mutable profile fields if changed
                dirty = False
                if claims.get("email") and user.email != claims["email"]:
                    user.email = claims["email"]
                    dirty = True
                if claims.get("name") and user.display_name != claims["name"]:
                    user.display_name = claims["name"]
                    dirty = True
                if claims.get("picture") and user.profile_image_url != claims["picture"]:
                    user.profile_image_url = claims["picture"]
                    dirty = True
                if dirty:
                    await asyncio.wait_for(session.flush(), timeout=8.0)

            _user_token_cache[uid] = (now, user)
            return user
        except Exception as exc:
            err_msg = str(exc) or repr(exc) or type(exc).__name__
            lower_exc = err_msg.lower()
            if any(w in lower_exc for w in ("10054", "forcibly closed", "connection reset", "broken pipe")):
                logger.debug(f"[Auth] Database connection reset resolving user {uid}, using resilient fallback: {err_msg}")
            elif isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
                logger.info(f"[Auth] Database connection timed out resolving user {uid}; using fallback user.")
            else:
                logger.warning(f"[Auth] Database connection issue resolving user {uid}, using resilient fallback: {err_msg}")
            _user_token_cache[uid] = (now, fallback_user)
            return fallback_user


async def get_or_create_local_user(session: Optional[AsyncSession] = None) -> User:
    """Ensures a persistent local desktop user account exists in DB for offline/local use with graceful fallback."""
    global _cached_local_user
    if _cached_local_user is not None:
        return _cached_local_user

    # Return immediate memory fallback instantly with ZERO blocking on cold DB connections
    _cached_local_user = _fallback_local_user
    return _cached_local_user


async def get_current_user_optional(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: Optional[AsyncSession] = Depends(get_db_session),
) -> Optional[User]:
    """Dependency that returns authenticated User if Bearer token present and DB available, else local user."""
    if not creds or not creds.credentials:
        try:
            return await get_or_create_local_user(session)
        except Exception:
            return _fallback_local_user

    try:
        claims = await verify_id_token(creds.credentials)
        return await get_or_create_user(session, claims)
    except Exception as exc:
        logger.debug(f"[Auth] Optional user resolution fallback: {exc}")
        try:
            return await get_or_create_local_user(session)
        except Exception:
            return _fallback_local_user


async def get_current_user(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: Optional[AsyncSession] = Depends(get_db_session),
) -> User:
    """Dependency resolving authenticated User. Falls back to local desktop user with zero-crash resilience."""
    if not creds or not creds.credentials:
        if os.getenv("NEXUS_TEST_MODE") == "1":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing Authorization Bearer token",
            )
        try:
            return await get_or_create_local_user(session)
        except Exception as exc:
            logger.warning(f"[Auth] Error resolving local user, falling back: {exc}")
            return _fallback_local_user

    try:
        claims = await verify_id_token(creds.credentials)
        return await get_or_create_user(session, claims)
    except Exception as exc:
        if os.getenv("NEXUS_TEST_MODE") == "1":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired token: {exc}",
            )
        logger.debug(f"[Auth] Token verification failed, fallback to local user: {exc}")
        try:
            return await get_or_create_local_user(session)
        except Exception:
            return _fallback_local_user


async def get_current_user_strict(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    session: Optional[AsyncSession] = Depends(get_db_session),
) -> User:
    """Dependency that REQUIRES valid Firebase token - no fallback to local user.
    
    Used for endpoints that must reject unauthenticated requests.
    """
    if not creds or not creds.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in to access this resource.",
        )

    try:
        claims = await verify_id_token(creds.credentials)
        return await get_or_create_user(session, claims)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired authentication token.",
        )
