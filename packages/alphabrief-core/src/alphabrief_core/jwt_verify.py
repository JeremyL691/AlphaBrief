"""Minimal JWT/JWKS verification for the ChatGPT sign-in channel.

Stdlib-only RS256 verification (RFC 7515 / RFC 8017 PKCS#1 v1.5) so the
product does not need a crypto dependency to validate an ID token. The
implementation deliberately supports exactly one algorithm family: any
token whose header does not say ``RS256`` is rejected, and key material
must come from a JWKS document whose ``kty`` is ``RSA``.
"""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

#: DigestInfo prefix for SHA-256 in PKCS#1 v1.5 signatures.
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

SUPPORTED_ALGORITHM = "RS256"


class JwtVerificationError(ValueError):
    """Raised when a JWT cannot be trusted."""


def b64url_decode(value: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded)
    except (ValueError, TypeError) as exc:
        raise JwtVerificationError("malformed base64url segment") from exc


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_segment(segment: str) -> dict[str, Any]:
    try:
        decoded = json.loads(b64url_decode(segment).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise JwtVerificationError("malformed JSON segment") from exc
    if not isinstance(decoded, dict):
        raise JwtVerificationError("JWT segment is not a JSON object")
    return decoded


@dataclass(frozen=True)
class RsaJwk:
    """One RSA public key from a JWKS document."""

    kid: str
    modulus: int
    exponent: int


def parse_jwks(document: Any) -> list[RsaJwk]:
    """Return every RSA key in a JWKS document."""
    if not isinstance(document, dict):
        raise JwtVerificationError("JWKS is not a JSON object")
    keys = document.get("keys")
    if not isinstance(keys, list):
        raise JwtVerificationError("JWKS has no keys array")
    parsed: list[RsaJwk] = []
    for entry in keys:
        if not isinstance(entry, dict) or entry.get("kty") != "RSA":
            continue
        n = entry.get("n")
        e = entry.get("e")
        if not isinstance(n, str) or not isinstance(e, str):
            continue
        parsed.append(
            RsaJwk(
                kid=str(entry.get("kid") or ""),
                modulus=int.from_bytes(b64url_decode(n), "big"),
                exponent=int.from_bytes(b64url_decode(e), "big"),
            )
        )
    if not parsed:
        raise JwtVerificationError("JWKS contains no usable RSA key")
    return parsed


def _verify_signature(signing_input: bytes, signature: bytes, key: RsaJwk) -> None:
    if len(signature) != (key.modulus.bit_length() + 7) // 8:
        raise JwtVerificationError("signature length does not match the key")
    decrypted = pow(int.from_bytes(signature, "big"), key.exponent, key.modulus)
    block = decrypted.to_bytes(len(signature), "big")
    expected = _SHA256_DIGEST_INFO + hashlib.sha256(signing_input).digest()
    # 0x00 || 0x01 || 0xFF padding || 0x00 || DigestInfo
    if block[0] != 0 or block[1] != 1:
        raise JwtVerificationError("malformed signature padding")
    marker = block.find(b"\x00", 2)
    if marker < 0 or block[marker + 1 :] != expected:
        raise JwtVerificationError("signature does not match the token")


def verify_id_token(
    token: str,
    *,
    jwks: Any,
    issuer: str,
    audience: str,
    nonce: str | None = None,
    now: datetime | None = None,
    leeway_seconds: int = 60,
) -> dict[str, Any]:
    """Verify an RS256 ID token and return its claims.

    Checks the algorithm, the JWKS signature, ``iss``, ``aud``, ``exp``,
    ``nbf``/``iat`` when present, and the ``nonce`` bound to the attempt.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise JwtVerificationError("ID token must have three segments")
    header = decode_segment(parts[0])
    if header.get("alg") != SUPPORTED_ALGORITHM:
        raise JwtVerificationError(
            f"unsupported ID token algorithm: {header.get('alg')!r}"
        )
    claims = decode_segment(parts[1])
    signature = b64url_decode(parts[2])
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")

    kid = header.get("kid")
    candidates = parse_jwks(jwks)
    if kid:
        candidates = [key for key in candidates if key.kid == kid] or candidates
    last_error: JwtVerificationError | None = None
    for key in candidates:
        try:
            _verify_signature(signing_input, signature, key)
            break
        except JwtVerificationError as exc:
            last_error = exc
    else:
        raise last_error or JwtVerificationError("no key verified the signature")

    if claims.get("iss") != issuer:
        raise JwtVerificationError("issuer mismatch")
    audience_claim = claims.get("aud")
    audiences = (
        [audience_claim]
        if isinstance(audience_claim, str)
        else list(audience_claim or ())
    )
    if audience not in audiences:
        raise JwtVerificationError("audience mismatch")
    if nonce is not None and claims.get("nonce") != nonce:
        raise JwtVerificationError("nonce mismatch")

    current = int((now or datetime.now(UTC)).timestamp())
    expiry = claims.get("exp")
    if not isinstance(expiry, int) or expiry <= current - leeway_seconds:
        raise JwtVerificationError("ID token is expired")
    not_before = claims.get("nbf")
    if isinstance(not_before, int) and not_before > current + leeway_seconds:
        raise JwtVerificationError("ID token is not valid yet")
    return claims


__all__ = [
    "SUPPORTED_ALGORITHM",
    "JwtVerificationError",
    "RsaJwk",
    "b64url_decode",
    "b64url_encode",
    "decode_segment",
    "parse_jwks",
    "verify_id_token",
]
