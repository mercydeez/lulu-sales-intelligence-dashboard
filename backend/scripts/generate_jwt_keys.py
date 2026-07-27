#!/usr/bin/env python3
"""
Generate an RS256 JWT signing keypair for E5-6 (JWT → RS256 + rotation).

Writes:
  <out-dir>/<kid>.key   the PRIVATE key (PKCS8 PEM) — feed to the vault / mount as
                        JWT_PRIVATE_KEY_PATH. NEVER commit this.
  <public-dir>/<kid>.pem the PUBLIC key (SPKI PEM) — drop into JWT_PUBLIC_KEYS_DIR
                        on every verifier so tokens with this kid validate.

Usage:
  python scripts/generate_jwt_keys.py --kid 2026-07 \
      --out-dir ./secrets/jwt --public-dir ./secrets/jwt/public

Rotation: generate a NEW kid, publish its .pem to every verifier's public dir
FIRST, then switch JWT_ACTIVE_KID (+ JWT_PRIVATE_KEY_PATH) to the new key. Keep the
old .pem until all tokens signed by it have expired, then remove it. Full procedure:
docs/runbooks/JWT_KEY_ROTATION.md.
"""
import argparse
import os
import sys

# Allow running from the backend dir without installing the package.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.jwt_keys import generate_rsa_keypair  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate an RS256 JWT keypair.")
    ap.add_argument("--kid", required=True, help="Key id (e.g. a date like 2026-07).")
    ap.add_argument("--out-dir", default="./secrets/jwt", help="Where to write the private key.")
    ap.add_argument("--public-dir", default=None,
                    help="Where to write the public key (default: <out-dir>/public).")
    ap.add_argument("--key-size", type=int, default=2048)
    args = ap.parse_args()

    public_dir = args.public_dir or os.path.join(args.out_dir, "public")
    os.makedirs(args.out_dir, exist_ok=True)
    os.makedirs(public_dir, exist_ok=True)

    private_pem, public_pem = generate_rsa_keypair(args.key_size)

    priv_path = os.path.join(args.out_dir, f"{args.kid}.key")
    pub_path = os.path.join(public_dir, f"{args.kid}.pem")

    # Private key: owner-read-only.
    fd = os.open(priv_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(private_pem)
    with open(pub_path, "w", encoding="utf-8") as fh:
        fh.write(public_pem)

    print(f"kid           : {args.kid}")
    print(f"private key   : {priv_path}   (0600 — load via JWT_PRIVATE_KEY_PATH; do NOT commit)")
    print(f"public key    : {pub_path}   (publish into JWT_PUBLIC_KEYS_DIR on every verifier)")
    print("")
    print("Next: set JWT_ALGORITHM=RS256, JWT_ACTIVE_KID=%s, JWT_PRIVATE_KEY_PATH=%s,"
          " JWT_PUBLIC_KEYS_DIR=%s" % (args.kid, priv_path, public_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
