from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_der_public_key


SIGNATURE_VERSION = "JIAOTANG-SIGNATURE-V1"
ENROLLMENT_VERSION = "JIAOTANG-ENROLLMENT-V1"
TRANSACTIONAL_ENROLLMENT_VERSION = "JIAOTANG-ENROLLMENT-TRANSACTION-V1"
ACTIVATION_VERSION = "JIAOTANG-ACTIVATION-V1"
KEY_ID_PATTERN = re.compile(r"^jdk_[A-Za-z0-9_-]{20,64}$")
NONCE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")


class DeviceSignatureError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceSignature:
    key_id: str
    timestamp: str
    nonce: str
    signature: str


def base64url_decode(value: str) -> bytes:
    candidate = value.strip()
    if not candidate or not re.fullmatch(r"[A-Za-z0-9_-]+", candidate):
        raise DeviceSignatureError("签名编码无效")
    try:
        return base64.urlsafe_b64decode(candidate + "=" * (-len(candidate) % 4))
    except (ValueError, TypeError) as exc:
        raise DeviceSignatureError("签名编码无效") from exc


def base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def request_body_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def request_canonical_value(
    *,
    method: str,
    request_target: str,
    timestamp: str,
    nonce: str,
    body_hash: str,
    token_fingerprint: str,
) -> bytes:
    return "\n".join(
        (
            SIGNATURE_VERSION,
            method.upper(),
            request_target,
            timestamp,
            nonce,
            body_hash,
            token_fingerprint,
        )
    ).encode("utf-8")


def enrollment_canonical_value(
    *,
    enrollment_code: str,
    device_id: str,
    device_name: str,
    platform: str,
    agent_host: str,
    public_key: str,
    transaction_mode: str = "legacy_v1",
) -> bytes:
    if transaction_mode == "credential_activation_v1":
        return "\n".join(
            (
                TRANSACTIONAL_ENROLLMENT_VERSION,
                enrollment_code,
                device_id,
                device_name,
                platform,
                agent_host,
                public_key,
                transaction_mode,
            )
        ).encode("utf-8")
    return "\n".join(
        (
            ENROLLMENT_VERSION,
            enrollment_code,
            device_id,
            device_name,
            platform,
            agent_host,
            public_key,
        )
    ).encode("utf-8")


def activation_canonical_value(
    *,
    enrollment_code: str,
    device_id: str,
    key_id: str,
    token_fingerprint: str,
) -> bytes:
    return "\n".join(
        (
            ACTIVATION_VERSION,
            enrollment_code,
            device_id,
            key_id,
            token_fingerprint,
        )
    ).encode("utf-8")


def load_ed25519_public_key(public_key: str) -> Ed25519PublicKey:
    encoded = base64url_decode(public_key)
    if len(encoded) > 256:
        raise DeviceSignatureError("设备公钥长度无效")
    try:
        key = load_der_public_key(encoded)
    except (ValueError, TypeError) as exc:
        raise DeviceSignatureError("设备公钥无效") from exc
    if not isinstance(key, Ed25519PublicKey):
        raise DeviceSignatureError("设备公钥算法必须为 Ed25519")
    return key


def device_key_id(public_key: str) -> str:
    encoded = base64url_decode(public_key)
    digest = hashlib.sha256(encoded).digest()[:18]
    return "jdk_" + base64url_encode(digest)


def verify_ed25519_signature(
    public_key: str,
    signature: str,
    message: bytes,
) -> None:
    key = load_ed25519_public_key(public_key)
    try:
        key.verify(base64url_decode(signature), message)
    except InvalidSignature as exc:
        raise DeviceSignatureError("设备签名验证失败") from exc
