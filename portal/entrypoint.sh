#!/bin/sh
# Runs migrations once, then whatever command was given.
set -e
cd /app/portal
python manage.py migrate --noinput
exec "$@"
