"""Thin wrapper over the Hetzner Cloud API. All calls go through here so a second
provider (OVH, Scaleway) can be added behind the same three functions."""

import logging
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

AGENT_PATH = Path(settings.BASE_DIR).parent / "compute" / "agent.py"
CLOUD_INIT_PATH = Path(settings.BASE_DIR).parent / "compute" / "cloud-init.yml"


def _client():
    from hcloud import Client

    if not settings.HCLOUD_TOKEN:
        raise RuntimeError("HCLOUD_TOKEN is not configured")
    return Client(token=settings.HCLOUD_TOKEN, application_name="fdsrun")


def user_data(job) -> str:
    """cloud-init that installs Docker, pulls the FDS image and starts the agent."""
    agent = AGENT_PATH.read_text()
    template = CLOUD_INIT_PATH.read_text()
    indented = "\n".join("      " + line for line in agent.splitlines())
    return (
        template.replace("__AGENT__", indented)
        .replace("__PORTAL_URL__", settings.PORTAL_URL)
        .replace("__JOB_ID__", job.public_id)
        .replace("__JOB_TOKEN__", job.agent_token)
        .replace("__IMAGE__", settings.COMPUTE_IMAGE)
    )


def create_server(job, name: str, server_type: str):
    from hcloud.images import Image
    from hcloud.server_types import ServerType
    from hcloud.locations import Location

    c = _client()
    resp = c.servers.create(
        name=name,
        server_type=ServerType(name=server_type),
        image=Image(name="ubuntu-24.04"),
        location=Location(name=settings.HCLOUD_LOCATION),
        user_data=user_data(job),
        labels={"app": settings.COMPUTE_LABEL, "job": job.public_id},
        public_net=None,
    )
    s = resp.server
    log.info("created server %s (%s) for job %s", s.id, s.public_net.ipv4.ip if s.public_net.ipv4 else "-", job.public_id)
    return s.id, (s.public_net.ipv4.ip if s.public_net.ipv4 else None)


def delete_server(hcloud_id: int) -> bool:
    from hcloud import APIException

    c = _client()
    try:
        server = c.servers.get_by_id(hcloud_id)
    except APIException as e:
        if getattr(e, "code", "") == "not_found":
            return True
        raise
    if server is None:
        return True
    server.delete()
    return True


def list_app_servers():
    """All servers carrying our label — the watchdog uses this to find forgotten machines."""
    c = _client()
    return c.servers.get_all(label_selector=f"app={settings.COMPUTE_LABEL}")


def server_running(hcloud_id: int):
    """True/False from Hetzner; None when Hetzner cannot be asked (then assume alive)."""
    try:
        s = _client().servers.get_by_id(hcloud_id)
    except Exception as e:  # noqa: BLE001
        if "not_found" in str(e).lower() or "404" in str(e):
            return False
        log.warning("hcloud: cannot check server %s: %s", hcloud_id, e)
        return None
    return s.status in ("running", "starting", "initializing")
