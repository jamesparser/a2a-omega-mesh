#!/usr/bin/env python3
"""mesh_seal.py - sealed payload helper for the a2a omega mesh (boss 11-02: 'finish encrypted').

Seals a mesh message body so ONLY the recipient principal can read it.
Signatures still happen at the transport layer (board enforces ed25519); this adds
payload confidentiality on top.

Envelope format (stored in the message 'body' field, opaque to the board):
  MSEALED1:<sender_principal>:<b64(x25519_sender_pub,32)>:<b64(nonce,12)>:<b64(ct)>

Crypto: X25519 ECDH -> HKDF-SHA256 -> AES-256-GCM.
Keys: ~/.openwork/mesh_seal/<principal>_x25519.json  {priv_b64, pub_b64}
Pubkeys are exchanged via the board roster file (added as *_x25519_pub fields by deploy script).

Usage:
  python3 mesh_seal.py genkey <principal>          # create keypair if missing, print pub
  python3 mesh_seal.py seal <sender> <recipient> <body-file-or-'-'>   # -> envelope string
  python3 mesh_seal.py open <principal> <envelope>                    # -> plaintext
"""
import base64, json, os, sys, hashlib

from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import serialization

KEYDIR = os.path.expanduser("~/.openwork/mesh_seal")
PREFIX = "MSEALED1"


def _keypath(principal):
    return os.path.join(KEYDIR, f"{principal}_x25519.json")


def genkey(principal, overwrite=False):
    os.makedirs(KEYDIR, exist_ok=True)
    p = _keypath(principal)
    if os.path.exists(p) and not overwrite:
        d = json.load(open(p))
        return d["pub_b64"]
    k = X25519PrivateKey.generate()
    priv = k.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    pub = k.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    d = {"priv_b64": base64.b64encode(priv).decode(), "pub_b64": base64.b64encode(pub).decode()}
    with open(p, "w") as f:
        json.dump(d, f)
    try:
        os.chmod(p, 0o600)
    except Exception:
        pass
    return d["pub_b64"]


def _load_priv(principal):
    p = _keypath(principal)
    if not os.path.exists(p):
        raise SystemExit(f"no key for {principal}; run: mesh_seal.py genkey {principal}")
    d = json.load(open(p))
    return base64.b64decode(d["priv_b64"])


def _load_pub_from_roster(principal, roster_path=None):
    """Recipient pubkey from the local roster copy (synced from omega board roster.json)."""
    candidates = [
        roster_path,
        os.path.expanduser("~/.openwork/mesh_seal/roster_x25519.json"),
        "/opt/mesh-board-prod-20261031/roster.json",
    ]
    for c in candidates:
        if not c or not os.path.exists(c):
            continue
        d = json.load(open(c))
        prins = d.get("principals", d)
        if isinstance(prins, dict):
            v = prins.get(principal)
            if isinstance(v, dict):
                pub = v.get("x25519_pub") or v.get("x25519_pub_b64")
                if pub:
                    return base64.b64decode(pub)
            elif isinstance(v, str) and len(v) > 20 and "." not in v:
                # raw b64 pubkey stored as the value
                try:
                    return base64.b64decode(v)
                except Exception:
                    pass
    # fallback: local file named <principal>.pub.b64
    p = os.path.join(KEYDIR, f"{principal}.pub.b64")
    if os.path.exists(p):
        return base64.b64decode(open(p).read().strip())
    raise SystemExit(f"no x25519 pubkey for {principal}; add to roster_x25519.json")


def _dh(priv_bytes, peer_pub_bytes):
    priv = X25519PrivateKey.from_private_bytes(priv_bytes)
    peer = X25519PublicKey.from_public_bytes(peer_pub_bytes)
    shared = priv.exchange(peer)
    hk = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"mesh-seal-v1", info=b"a2a-omega-mesh")
    return hk.derive(shared)


def seal(sender, recipient, plaintext: bytes) -> str:
    sender_priv = _load_priv(sender)
    recip_pub = X25519PublicKey.from_public_bytes(_load_pub_from_roster(recipient))
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    # ECDH with ephemeral key against recipient pub -> both sides derive same key:
    # recipient does ECDH(own_priv, eph_pub)
    shared = eph.exchange(recip_pub)
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"mesh-seal-v1", info=b"a2a-omega-mesh").derive(shared)
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, b"msea1|" + sender.encode()[:32])
    env = ":".join([
        PREFIX,
        sender,
        base64.b64encode(eph_pub).decode(),
        base64.b64encode(nonce).decode(),
        base64.b64encode(ct).decode(),
    ])
    return env


def open_sealed(principal, envelope: str) -> bytes:
    parts = envelope.split(":")
    if parts[0] != PREFIX or len(parts) != 5:
        raise ValueError("not a MSEALED1 envelope")
    _, sender, eph_pub_b64, nonce_b64, ct_b64 = parts
    recip_priv = X25519PrivateKey.from_private_bytes(_load_priv(principal))
    eph_pub = base64.b64decode(eph_pub_b64)
    shared = recip_priv.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"mesh-seal-v1", info=b"a2a-omega-mesh").derive(shared)
    return AESGCM(key).decrypt(base64.b64decode(nonce_b64), base64.b64decode(ct_b64), b"msea1|" + sender.encode()[:32])


if __name__ == "__main__":
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PublicKey  # noqa

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "genkey":
        print(genkey(sys.argv[2]))
    elif cmd == "seal":
        data = sys.stdin.buffer.read()
        print(seal(sys.argv[2], sys.argv[3], data))
    elif cmd == "open":
        env_data = sys.stdin.read().strip() if not sys.stdin.isatty() else sys.argv[3]
        sys.stdout.buffer.write(open_sealed(sys.argv[2], env_data))
    else:
        print(__doc__)
