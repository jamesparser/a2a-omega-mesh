#!/usr/bin/env python3
import sys, json, base64, os
sys.path.insert(0, "/opt/mesh-board-prod-20261031")
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

sender, recipient = sys.argv[1], sys.argv[2]
roster = json.load(open("/opt/mesh-board-prod-20261031/roster_x25519.json"))
recip_pub_b64 = roster["principals"][recipient]["x25519_pub"]
kp_file = f"/opt/mesh-board-prod-20261031/keys_{sender}.json"
sender_kp = json.load(open(kp_file))
sender_priv = X25519PrivateKey.from_private_bytes(base64.b64decode(sender_kp["priv_b64"]))
eph = X25519PrivateKey.generate()
eph_pub = eph.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
shared = eph.exchange(X25519PublicKey.from_public_bytes(base64.b64decode(recip_pub_b64)))
key = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"mesh-seal-v1", info=b"a2a-omega-mesh").derive(shared)
nonce = os.urandom(12)
body = sys.stdin.buffer.read()
ct = AESGCM(key).encrypt(nonce, body, b"msea1|" + sender.encode()[:32])
env = ":".join(["MSEALED1", sender,
    base64.b64encode(eph_pub).decode(), base64.b64encode(nonce).decode(), base64.b64encode(ct).decode()])
print(env)
