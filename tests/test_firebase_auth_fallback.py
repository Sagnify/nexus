import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.core.firebase_auth import verify_id_token


class TestFirebaseTokenVerificationFallback(unittest.IsolatedAsyncioTestCase):
    async def test_public_certificate_verifier_handles_missing_admin_credentials(self):
        claims = {
            "sub": "firebase-user-1",
            "email": "person@example.com",
            "name": "Person",
            "picture": "https://example.com/avatar.png",
        }
        with (
            patch("backend.core.firebase_auth.initialize_firebase_admin"),
            patch("backend.core.firebase_auth.fb_auth.verify_id_token", side_effect=RuntimeError("ADC unavailable")),
            patch("google.oauth2.id_token.verify_firebase_token", return_value=claims) as public_verifier,
        ):
            result = await verify_id_token("header.payload.signature")

        self.assertEqual(result["uid"], "firebase-user-1")
        self.assertEqual(result["email"], "person@example.com")
        public_verifier.assert_called_once()
        self.assertEqual(public_verifier.call_args.kwargs["audience"], "nexus-9290d")

    async def test_invalid_token_is_rejected_when_both_verifiers_fail(self):
        with (
            patch("backend.core.firebase_auth.initialize_firebase_admin"),
            patch("backend.core.firebase_auth.fb_auth.verify_id_token", side_effect=RuntimeError("ADC unavailable")),
            patch("google.oauth2.id_token.verify_firebase_token", side_effect=ValueError("bad signature")),
        ):
            with self.assertRaises(HTTPException) as raised:
                await verify_id_token("invalid.token.value")

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()