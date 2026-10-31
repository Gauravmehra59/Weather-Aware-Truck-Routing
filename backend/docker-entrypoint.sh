#!/bin/sh
set -e

# Ensure parent directory for database exists if custom path is set
if [ -n "$DJANGO_DB_PATH" ]; then
    mkdir -p "$(dirname "$DJANGO_DB_PATH")"
fi

echo "Running Django migrations..."
python manage.py migrate --noinput

echo "Collecting static files for WhiteNoise..."
python manage.py collectstatic --noinput

exec "$@"
