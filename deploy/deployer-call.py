#!/usr/bin/env python3
"""Call a deployer endpoint from GitHub Actions: deployer-call.py <ip> <path> '<json>'"""
import hashlib, hmac, json, os, sys, time, urllib.request

ip, path, payload = sys.argv[1], sys.argv[2], json.loads(sys.argv[3] if len(sys.argv) > 3 else "{}")
payload["ts"] = time.time()
body = json.dumps(payload).encode()
key = hashlib.sha256(f"fdsrun-deployer:{os.environ['HCLOUD_TOKEN']}".encode()).hexdigest().encode()
sig = hmac.new(key, body, hashlib.sha256).hexdigest()
req = urllib.request.Request(f"https://{ip}.sslip.io{path}", data=body, headers={"Content-Type": "application/json", "X-Signature": sig}, method="POST")
with urllib.request.urlopen(req, timeout=900) as r:
    print(r.read().decode())
