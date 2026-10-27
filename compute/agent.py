#!/usr/bin/env python3
"""
fdsrun compute agent. Runs on the compute machine (delivered by cloud-init),
talks only to the portal, needs nothing but Python 3 and Docker.

Flow: fetch job spec and input -> pull FDS image -> run FDS under MPI ->
report progress every 10 s and upload small result files every 60 s ->
upload everything at the end -> report finish. The portal then deletes the machine.
"""

import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

CONF = "/etc/fdsrun-agent.env"
WORK = "/work"
LOG = "/var/log/fdsrun-agent.log"
HEARTBEAT_S = 10
UPLOAD_EVERY_S = 60
SMALL_FILE_LIMIT = 64 * 1024 * 1024
STOP_GRACE_S = 300

# two .out formats: verbose blocks ("Time Step  N  <date>\n Step Size: X s, Total Time: T s")
# and compact lines ("Time Step: N, Simulation Time: T s, Step Size: X s")
STEP_RES = [
    re.compile(r"Time Step\s+(\d+)\s+\w+ \d+, \d{4}\s+[\d:]+\s+Step Size:\s+([\d.E+-]+)\s*s,\s+Total Time:\s+([\d.]+)\s*s", re.S),
    re.compile(r"Time Step:\s+(\d+),\s+Simulation Time:\s+([\d.]+)\s*s,\s+Step Size:\s+([\d.E+-]+)\s*s"),
]


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def load_conf():
    conf = {}
    with open(CONF) as f:
        for line in f:
            if "=" in line and not line.startswith("#"):
                k, v = line.strip().split("=", 1)
                conf[k] = v.strip('"')
    return conf


class Portal:
    def __init__(self, base, job_id, token):
        self.base = base.rstrip("/")
        self.job_id = job_id
        self.headers = {"Authorization": f"Bearer {token}"}

    def _url(self, path):
        return f"{self.base}/api/compute/jobs/{self.job_id}/{path}"

    def json(self, path, payload=None, retries=5):
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self._url(path), data=data, headers={**self.headers, "Content-Type": "application/json"}, method="POST" if data is not None else "GET")
        for i in range(retries):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.loads(r.read() or b"{}")
            except urllib.error.HTTPError as e:
                if e.code == 403:
                    raise SystemExit(f"portal refused us ({e.code}); giving up")
                log(f"portal {path}: HTTP {e.code}, retry {i + 1}")
            except Exception as e:  # noqa: BLE001
                log(f"portal {path}: {e}, retry {i + 1}")
            time.sleep(5 * (i + 1))
        raise RuntimeError(f"portal unreachable: {path}")

    def download(self, path, dest):
        req = urllib.request.Request(self._url(path), headers=self.headers)
        with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)

    def upload(self, local_path, name, retries=3):
        u = urllib.parse.urlparse(self._url("files/" + urllib.parse.quote(name)))
        size = os.path.getsize(local_path)
        for i in range(retries):
            try:
                conn = (http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection)(u.netloc, timeout=600)
                with open(local_path, "rb") as f:
                    conn.request("POST", u.path, body=f, headers={**self.headers, "Content-Type": "application/octet-stream", "Content-Length": str(size)})
                resp = conn.getresponse()
                body = resp.read()
                conn.close()
                if resp.status == 200:
                    return True
                log(f"upload {name}: HTTP {resp.status} {body[:200]!r}")
            except Exception as e:  # noqa: BLE001
                log(f"upload {name}: {e}")
            time.sleep(10 * (i + 1))
        return False


def tail(path, n=60):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 16000))
            lines = f.read().decode("utf-8", "replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def parse_last_step(text):
    best = None
    for i, rx in enumerate(STEP_RES):
        for m in rx.finditer(text):
            step = int(m.group(1))
            if best is None or step > best["step"]:
                dt, t = (m.group(2), m.group(3)) if i == 0 else (m.group(3), m.group(2))
                best = {"step": step, "t": float(t), "dt": float(dt)}
    return best


def last_step(out_path):
    return parse_last_step(tail(out_path, 400))


def run(cmd, **kw):
    log("$ " + " ".join(cmd))
    return subprocess.run(cmd, **kw)


class Uploader:
    def __init__(self, portal, exclude):
        self.portal = portal
        self.exclude = set(exclude)
        self.sent = {}  # name -> (size, mtime)

    def sync(self, final=False):
        for name in sorted(os.listdir(WORK)):
            p = os.path.join(WORK, name)
            if name in self.exclude or not os.path.isfile(p) or name.endswith(".part"):
                continue
            st = os.stat(p)
            sig = (st.st_size, int(st.st_mtime))
            if self.sent.get(name) == sig:
                continue
            if not final and st.st_size > SMALL_FILE_LIMIT:
                continue
            if not final and time.time() - st.st_mtime < 3:
                continue  # still being written
            if self.portal.upload(p, name):
                self.sent[name] = sig


def main():
    conf = load_conf()
    portal = Portal(conf["PORTAL_URL"], conf["JOB_ID"], conf["JOB_TOKEN"])
    image = conf["IMAGE"]
    os.makedirs(WORK, exist_ok=True)
    started = time.time()

    def progress(phase, **extra):
        payload = {"phase": phase, "wall_s": time.time() - started, **extra}
        try:
            return portal.json("progress", payload).get("action", "continue")
        except Exception as e:  # noqa: BLE001
            log(f"progress failed: {e}")
            return "continue"

    try:
        progress("preparing", message="Pobieram model i obraz FDS")
        spec = portal.json("spec")
        fds_file = spec["filename"]
        chid = spec.get("chid") or os.path.splitext(fds_file)[0]
        procs = int(spec["procs"])
        portal.download("input", os.path.join(WORK, fds_file))
        log(f"job {spec['job_id']}: {fds_file}, chid={chid}, procs={procs}")

        for i in range(10):
            if run(["docker", "pull", image], capture_output=True).returncode == 0:
                break
            progress("preparing", message=f"Pobieram obraz FDS (próba {i + 2})")
            time.sleep(15)
        else:
            raise RuntimeError("cannot pull FDS image")

        nproc = os.cpu_count() or procs
        if procs > nproc:
            log(f"requested {procs} processes but machine has {nproc} vCPU; using {nproc}")
            procs = nproc
        fds_log = open(os.path.join(WORK, "fds_stdout.log"), "ab")
        proc = subprocess.Popen(
            # --ipc=host: Intel MPI exchanges data through /dev/shm; Docker's default 64 MB
            # overflows with many ranks and kills a rank with SIGBUS.
            ["docker", "run", "--rm", "--name", "fds", "--ipc=host", "-v", f"{WORK}:/work", "-w", "/work", image,
             "mpiexec", "-n", str(procs), "fds", fds_file],
            stdout=fds_log, stderr=subprocess.STDOUT,
        )
        progress("preparing", message=f"FDS wystartował na {procs} procesach")
        out_path = os.path.join(WORK, f"{chid}.out")
        uploader = Uploader(portal, exclude=[fds_file, "fds_stdout.log"])
        last_upload = time.time()
        stop_sent_at = None
        paused = False
        while proc.poll() is None:
            time.sleep(HEARTBEAT_S)
            st = last_step(out_path) or {}
            action = progress("paused" if paused else "running", out_tail=tail(out_path, 40), log_tail=tail(os.path.join(WORK, "fds_stdout.log"), 20), **st)
            if action == "pause" and not paused:
                log("portal asked to pause (cost cap)")
                run(["docker", "pause", "fds"], capture_output=True)
                paused = True
            elif action != "pause" and paused:
                log("resuming")
                run(["docker", "unpause", "fds"], capture_output=True)
                paused = False
            if action == "stop" and stop_sent_at is None:
                log("stop requested: writing stop file")
                open(os.path.join(WORK, f"{chid}.stop"), "w").close()
                stop_sent_at = time.time()
            if stop_sent_at and time.time() - stop_sent_at > STOP_GRACE_S:
                log("FDS did not stop in time, killing container")
                run(["docker", "kill", "fds"], capture_output=True)
            if time.time() - last_upload > UPLOAD_EVERY_S:
                uploader.sync()
                last_upload = time.time()
        rc = proc.returncode
        if rc != 0:
            # machine state for diagnostics: memory and recent kernel messages (OOM kills show here)
            for cmd in (["free", "-m"], ["sh", "-c", "dmesg 2>/dev/null | tail -n 40"], ["nproc"]):
                try:
                    out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
                    fds_log.write(f"\n--- {' '.join(cmd)} ---\n{out}".encode())
                except Exception:  # noqa: BLE001
                    pass
        fds_log.close()
        out_text = tail(out_path, 30)
        progress("finishing", message="Zapisuję wyniki", out_tail=out_text)
        uploader.sync(final=True)
        uploader.exclude.discard("fds_stdout.log")
        uploader.sync(final=True)
        ok = rc == 0 and "completed successfully" in out_text
        stopped = "stopped by user" in out_text or stop_sent_at is not None
        if ok:
            status, message = "done", "FDS zakończył obliczenia"
        elif stopped:
            status, message = "stopped", "Obliczenia zatrzymane"
        else:
            lines = tail(os.path.join(WORK, "fds_stdout.log"), 80).splitlines() + tail(out_path, 80).splitlines()
            err = [l.strip() for l in lines if re.match(r"\s*ERROR", l)]
            message = (err[0] if err else f"FDS zakończył się bez wyniku (kod {rc})")[:500]
            status = "failed"
        portal.json("finish", {"status": status, "message": message, "wall_s": time.time() - started})
        log(f"finished: {status} {message}")
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        log(f"agent error: {e}")
        try:
            portal.json("finish", {"status": "failed", "message": f"Błąd agenta: {e}"[:500], "wall_s": time.time() - started})
        except Exception:  # noqa: BLE001
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
