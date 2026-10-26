# Portal image: Django + gunicorn + Node (for analyzer/cli.js). Same image runs web, worker and beat.
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 FDSRUN_ENV=staging
RUN apt-get update && apt-get install -y --no-install-recommends nodejs curl && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 app
WORKDIR /app
COPY portal/requirements.txt /app/portal/requirements.txt
RUN pip install -r /app/portal/requirements.txt
COPY analyzer /app/analyzer
COPY compute /app/compute
COPY portal /app/portal
WORKDIR /app/portal
RUN DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput -v0 \
 && mkdir -p /data/jobs && chown -R app:app /app /data
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fs http://localhost:8000/healthz || exit 1
CMD ["gunicorn", "fdsrun.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "600", "--access-logfile", "-"]
