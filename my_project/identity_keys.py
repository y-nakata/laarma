"""
identity_keys.py — デモ/ベンチマーク用の Ed25519 鍵ペア生成・読み込み。

laarma SDK は秘密鍵を生成・保管しない（検証者であって発行者ではない。
docs/design/identity-signing.md §4）。鍵の生成・管理は SDK の外側、
このプロジェクト（デモ用の自己生成鍵・第1段階）が担う。
"""

from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def load_or_create_keypair(keys_dir: Path, name: str) -> Ed25519PrivateKey:
    """
    ``keys_dir/{name}.key`` があれば読み込み、無ければ生成して保存する。
    対応する公開鍵 ``keys_dir/{name}.pub`` も常に書き出す
    （runtime 側が AARM_IDENTITY_PUBKEY_DIR から同じファイル名で検証鍵を読む）。
    """
    keys_dir.mkdir(parents=True, exist_ok=True)
    private_path = keys_dir / f"{name}.key"
    public_path = keys_dir / f"{name}.pub"

    if private_path.is_file():
        private_key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    else:
        private_key = Ed25519PrivateKey.generate()
        private_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    public_path.write_bytes(
        private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_key
