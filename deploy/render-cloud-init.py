#!/usr/bin/env python3
"""Fill deploy/cloud-init.yml with secrets and embedded files. Output goes to stdout."""

import os
import secrets


def indent(text, n=6):
    return "\n".join((" " * n + line) if line.strip() else "" for line in text.splitlines())


env = os.environ
template = open("deploy/cloud-init.yml").read()
out = (
    template.replace("__FDSRUN_ENV__", env.get("FDSRUN_ENV", "staging"))
    .replace("__HCLOUD_TOKEN__", env["HCLOUD_TOKEN"])
    .replace("__LOCATION__", env.get("LOCATION", "nbg1"))
    .replace("__DJANGO_SECRET_KEY__", secrets.token_urlsafe(48))
    .replace("__POSTGRES_PASSWORD__", secrets.token_urlsafe(24))
    .replace("__IMAGE__", env["IMAGE"])
    .replace("__COMPUTE_IMAGE__", env["COMPUTE_IMAGE"])
    .replace("__DOMAIN__", env.get("DOMAIN", "staging.fdsrun.com"))
    .replace("__COMPOSE__", indent(open("deploy/compose.yml").read()))
    .replace("__CADDYFILE__", indent(open("deploy/Caddyfile").read()))
    .replace("__DEPLOYER__", indent(open("deploy/deployer/deployer.py").read()))
)
print(out)
