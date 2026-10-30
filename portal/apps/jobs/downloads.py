"""Download endpoints.

/pobierz/<id>/<name>[?t=token]  — in production Caddy owns this path: it calls
/api/download/auth (forward_auth) and, if allowed, serves the file itself with Range support.
Outside Caddy (dev, tests) the Django view below streams the file, also honouring Range.
"""
import mimetypes
import os
import re
from urllib.parse import parse_qs, unquote, urlsplit

from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET

from . import archives
from .models import Job, log_event


def _allowed(request, job, name, token):
    if token:
        return archives.check_token(token, job, name)
    user = request.user
    return user.is_authenticated and (job.owner_id == user.id or user.is_staff)


@require_GET
def download_auth(request):
    """Answer Caddy's forward_auth: 200 + X-Fdsrun-Path when the caller may download the file."""
    uri = request.headers.get("X-Forwarded-Uri", "")
    parts = urlsplit(uri)
    m = re.fullmatch(r"/pobierz/([A-Za-z0-9]+)/([^/]+)/?", parts.path)
    if not m:
        return HttpResponse(status=404)
    public_id, name = m.group(1), unquote(m.group(2))
    token = parse_qs(parts.query).get("t", [""])[0]
    job = Job.objects.filter(public_id=public_id).first()
    if not job:
        return HttpResponse(status=404)
    if not _allowed(request, job, name, token):
        return HttpResponse(status=403)
    found = archives.resolve(job, name)
    if not found:
        return HttpResponse(status=404)
    _, rel = found
    actor = request.user.email if request.user.is_authenticated else "link"
    log_event(job, "download", name, actor=actor)
    resp = HttpResponse(status=200)
    resp["X-Fdsrun-Path"] = rel
    resp["X-Fdsrun-Name"] = name
    return resp


def _file_iter(fh, start, length, chunk=1 << 20):
    fh.seek(start)
    left = length
    while left > 0:
        data = fh.read(min(chunk, left))
        if not data:
            break
        left -= len(data)
        yield data


@require_GET
def download(request, public_id, name):
    """Dev/test fallback for /pobierz/: streams the file with HTTP Range support."""
    job = get_object_or_404(Job, public_id=public_id)
    token = request.GET.get("t", "")
    if not _allowed(request, job, name, token):
        return HttpResponseForbidden("Brak dostępu do pliku")
    found = archives.resolve(job, name)
    if not found:
        raise Http404
    path, _ = found
    size = os.path.getsize(path)
    ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
    rng = request.headers.get("Range", "")
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng)
    if m and (m.group(1) or m.group(2)):
        start = int(m.group(1)) if m.group(1) else max(0, size - int(m.group(2)))
        end = int(m.group(2)) if m.group(1) and m.group(2) else size - 1
        end = min(end, size - 1)
        if start > end:
            resp = HttpResponse(status=416)
            resp["Content-Range"] = f"bytes */{size}"
            return resp
        fh = open(path, "rb")
        resp = StreamingHttpResponse(_file_iter(fh, start, end - start + 1), status=206, content_type=ctype)
        resp["Content-Range"] = f"bytes {start}-{end}/{size}"
        resp["Content-Length"] = str(end - start + 1)
    else:
        resp = FileResponse(open(path, "rb"), content_type=ctype)
        resp["Content-Length"] = str(size)
    resp["Accept-Ranges"] = "bytes"
    resp["Content-Disposition"] = f'attachment; filename="{name}"'
    log_event(job, "download", name, actor=request.user.email if request.user.is_authenticated else "link")
    return resp


@require_GET
def share_links(request, public_id):
    """HTMX fragment: signed links (7 days, no login) for the archives, with resume hints."""
    job = get_object_or_404(Job, public_id=public_id)
    if job.owner_id != request.user.id and not request.user.is_staff:
        raise Http404
    items = [dict(a, url=archives.download_url(job, a["name"], request, signed=True)) for a in archives.ready_archives(job)]
    log_event(job, "share_links", ", ".join(a["name"] for a in items), actor=request.user.email)
    return render(request, "jobs/_share.html", {"job": job, "items": items, "days": archives.LINK_MAX_AGE // 86400})
