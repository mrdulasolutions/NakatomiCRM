"""Unit tests for stored-secret encryption (no DB)."""

from __future__ import annotations

from app.security import decrypt_stored_secret, encrypt_stored_secret


def test_encrypt_decrypt_roundtrip():
    enc = encrypt_stored_secret("hunter22secret")
    assert enc is not None
    assert enc.startswith("enc:v1:")
    assert decrypt_stored_secret(enc) == "hunter22secret"


def test_decrypt_legacy_plaintext():
    assert decrypt_stored_secret("plain-old") == "plain-old"
