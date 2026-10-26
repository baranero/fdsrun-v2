"""TOTP two-factor authentication (Google Authenticator, Aegis, 1Password...)."""

import base64
import hashlib
import io
import secrets

import pyotp
import qrcode
import qrcode.image.svg

ISSUER = "fdsrun"


def new_secret():
    return pyotp.random_base32()


def provisioning_uri(user, secret):
    return pyotp.TOTP(secret).provisioning_uri(name=user.email, issuer_name=ISSUER)


def qr_svg_data_uri(uri):
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()


def verify(secret, code):
    code = (code or "").replace(" ", "")
    return bool(secret) and pyotp.TOTP(secret).verify(code, valid_window=1)


def make_backup_codes(n=8):
    return [secrets.token_hex(4) for _ in range(n)]


def hash_code(code):
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()[:24]


def use_backup_code(user, code):
    hashes = [h for h in user.totp_backup.split(",") if h]
    h = hash_code(code)
    if h in hashes:
        hashes.remove(h)
        user.totp_backup = ",".join(hashes)
        user.save(update_fields=["totp_backup"])
        return True
    return False
