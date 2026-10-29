#!/usr/bin/env python3
"""Run by GitHub Actions: sends a signed update to the deployer on the portal server
and waits until the new version answers on /healthz."""

import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

token = os.environ["HCLOUD_TOKEN"]
ip = os.environ["SERVER_IP"]
image = os.environ["IMAGE_TAG"]
domain = os.environ.get("PORTAL_DOMAIN", "").strip()
host = f"{ip}.sslip.io"
base = f"https://{host}"
key = hashlib.sha256(f"fdsrun-deployer:{token}".encode()).hexdigest().encode()

env = {}
# application secrets kept in GitHub (see docs/sekrety.md); only non-empty ones are sent
for name in ("EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL", "ADMIN_EMAIL", "COMPANY_NAME", "COMPANY_ADDRESS", "COMPANY_NIP", "COMPANY_EMAIL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET", "ING_API_KEY"):
    if os.environ.get("APP_" + name):
        env[name] = os.environ["APP_" + name]
if domain:
    # real DNS exists: make the real domain primary, keep sslip as a fallback
    env.update({"PORTAL_DOMAINS": f"{domain}, {host}", "PORTAL_URL": f"https://{domain}"})

payload = {
    "ts": time.time(),
    "image": image,
    "registry_user": os.environ.get("REGISTRY_USER", "github"),
    "registry_token": os.environ.get("REGISTRY_TOKEN", ""),
    "files": {"compose.yml": open("deploy/compose.yml").read(), "Caddyfile": open("deploy/Caddyfile").read(), "deployer.py": open("deploy/deployer/deployer.py").read()},
    "env": env,
}
body = json.dumps(payload).encode()
sig = hmac.new(key, body, hashlib.sha256).hexdigest()


def post(path, data, signature, timeout=900):
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json", "X-Signature": signature}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.loads(r.read())


for attempt in range(6):
    try:
        status, resp = post("/_deploy/update", body, sig)
        print(resp.get("log", ""))
        if not resp.get("ok"):
            print("::error::deployer reported a failure")
            sys.exit(1)
        break
    except urllib.error.HTTPError as e:
        print(f"deployer HTTP {e.code}: {e.read()[:500]}")
        if e.code in (403, 400):
            sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"deployer not reachable yet ({e}); waiting")
    time.sleep(30)
else:
    print("::error::could not reach the deployer")
    sys.exit(1)

print("waiting for the portal to come up...")
for _ in range(40):
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=10) as r:
            if r.status == 200:
                print(f"portal is up: {base}")
                if domain:
                    print(f"primary domain: https://{domain}")
                sys.exit(0)
    except Exception:  # noqa: BLE001
        pass
    time.sleep(10)
print("::error::portal did not become healthy")
sys.exit(1)
