#!/usr/bin/env python3
"""
fdsrun deployer: a tiny HTTP service on the portal server that lets GitHub Actions
update the running stack without SSH.

Every request body is signed with HMAC-SHA256 using a key derived from HCLOUD_TOKEN
(known to GitHub Actions as a secret and to this server via cloud-init). Nothing else
can trigger an update. Requests older than 5 minutes are rejected.

Endpoints (behind Caddy at https://<domain>/_deploy/...):
  POST /_deploy/update   {ts, image, registry_user, registry_token, files:{name:text}, env:{KEY:VAL}}
  POST /_deploy/status   {ts}   -> compose ps + recent logs
  POST /_deploy/manage   {ts, args:[...]} -> runs an allow-listed manage.py command in the web container
"""

import hashlib
import hmac
import json
import os
import re
import subprocess
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STACK_DIR = "/opt/fdsrun"
ENV_FILE = os.path.join(STACK_DIR, ".env")
ALLOWED_FILES = {"compose.yml", "Caddyfile", "deployer.py"}
ALLOWED_ENV = {"IMAGE", "PORTAL_DOMAINS", "PORTAL_URL", "COMPUTE_IMAGE", "FDSRUN_ENV", "HCLOUD_LOCATION", "EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL", "ADMIN_EMAIL", "COMPANY_NAME", "COMPANY_ADDRESS", "COMPANY_NIP", "COMPANY_EMAIL", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET", "MS_CLIENT_ID", "MS_CLIENT_SECRET", "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET", "ING_API_KEY", "COMPANY_BANK_ACCOUNT"}
SECRET_ENV = {k for k in ALLOWED_ENV if k.endswith(("PASSWORD", "SECRET", "_KEY"))}
MAX_SKEW_S = 300
ALLOWED_MANAGE = {"smoke_test", "job_status", "job_log", "job_rate", "job_retry", "job_stop", "jobs_list", "promote_admin", "purge_jobs", "keys_check", "build_archives", "send_test_mail", "share_link", "migrate", "showmigrations"}


def read_env():
    env = {}
    if os.path.exists(ENV_FILE):
        for line in open(ENV_FILE):
            if "=" in line and not line.startswith("#"):
                k, v = line.rstrip("\n").split("=", 1)
                env[k] = v
    return env


def write_env(env):
    tmp = ENV_FILE + ".tmp"
    with open(tmp, "w") as f:
        for k, v in sorted(env.items()):
            f.write(f"{k}={v}\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, ENV_FILE)


def signing_key():
    token = read_env().get("HCLOUD_TOKEN", "")
    return hashlib.sha256(f"fdsrun-deployer:{token}".encode()).hexdigest().encode()


def sh(cmd, timeout=900):
    p = subprocess.run(cmd, cwd=STACK_DIR, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout + p.stderr)[-20000:]


def compose(*args, timeout=900):
    return sh(["docker", "compose", "--env-file", ENV_FILE, *args], timeout=timeout)


class Handler(BaseHTTPRequestHandler):
    server_version = "fdsrun-deployer/1"

    def _reply(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _verify(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        sig = self.headers.get("X-Signature", "")
        expected = hmac.new(signing_key(), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            self._reply(403, {"error": "bad signature"})
            return None
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._reply(400, {"error": "bad json"})
            return None
        if abs(time.time() - float(data.get("ts", 0))) > MAX_SKEW_S:
            self._reply(403, {"error": "stale request"})
            return None
        return data

    def do_POST(self):
        if self.path == "/_deploy/status":
            if self._verify() is None:
                return
            _, ps = compose("ps", "--format", "table {{.Service}}\t{{.Status}}\t{{.Image}}")
            _, logs = compose("logs", "--tail", "80", "web", "worker", "caddy", timeout=60)
            self._reply(200, {"ps": ps, "logs": logs, "env": {k: ("***" if k in SECRET_ENV else v) for k, v in read_env().items() if k in ALLOWED_ENV}})
            return
        if self.path == "/_deploy/manage":
            data = self._verify()
            if data is None:
                return
            args = [str(a) for a in data.get("args") or []]
            import re
            if not args or args[0] not in ALLOWED_MANAGE or any(a.startswith("-") and not re.fullmatch(r"--[a-z][a-z-]*", a) for a in args):
                self._reply(400, {"error": "command not allowed"})
                return
            rc, out = compose("exec", "-T", "web", "python", "manage.py", *args, timeout=600)
            self._reply(200, {"rc": rc, "output": out})
            return
        if self.path != "/_deploy/update":
            self._reply(404, {"error": "unknown endpoint"})
            return
        data = self._verify()
        if data is None:
            return
        log = []
        restart_self = False
        for name, text in (data.get("files") or {}).items():
            if name in ALLOWED_FILES:
                path = os.path.join(STACK_DIR, name)
                if name == "deployer.py" and os.path.exists(path) and open(path).read() == text:
                    continue
                with open(path, "w") as f:
                    f.write(text)
                log.append(f"wrote {name}")
                restart_self = restart_self or name == "deployer.py"
        env = read_env()
        # the request is signed, so a new deployer.py in it may widen the allow-list right away
        # (otherwise new secrets would only arrive on the deploy after next)
        allowed = set(ALLOWED_ENV)
        new_code = (data.get("files") or {}).get("deployer.py", "")
        m = re.search(r"^ALLOWED_ENV = \{([^}]*)\}", new_code, re.M)
        if m:
            allowed |= set(re.findall(r'"([A-Z0-9_]+)"', m.group(1)))
        for k, v in (data.get("env") or {}).items():
            if k in allowed and isinstance(v, str):
                env[k] = v
        if data.get("image"):
            env["IMAGE"] = data["image"]
        write_env(env)
        if data.get("registry_token"):
            p = subprocess.run(["docker", "login", "ghcr.io", "-u", data.get("registry_user", "github"), "--password-stdin"], input=data["registry_token"], capture_output=True, text=True, timeout=60)
            log.append(f"login rc={p.returncode} {p.stderr.strip()[-200:]}")
        rc, out = compose("pull", "--quiet")
        log.append(f"pull rc={rc}\n{out[-2000:]}")
        rc2, out2 = compose("up", "-d", "--remove-orphans")
        log.append(f"up rc={rc2}\n{out2[-3000:]}")
        sh(["docker", "image", "prune", "-f"], timeout=300)
        if restart_self:
            log.append("deployer updated, restarting itself")
            subprocess.Popen(["sh", "-c", "sleep 2; systemctl restart fdsrun-deployer"])
        self._reply(200 if rc == 0 and rc2 == 0 else 500, {"ok": rc == 0 and rc2 == 0, "log": "\n".join(log)})

    def log_message(self, fmt, *args):  # quieter journal
        if "/_deploy/" in fmt % args:
            super().log_message(fmt, *args)


if __name__ == "__main__":
    os.makedirs(STACK_DIR, exist_ok=True)
    ThreadingHTTPServer(("0.0.0.0", 9000), Handler).serve_forever()
