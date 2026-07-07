# DigitalOcean App Platform (and other buildpack hosts) read this.
# The web process MUST be ASGI (uvicorn) — this app uses Django Channels for
# WebSockets (live trips, chat, notifications, SOS). The buildpack default of
# `gunicorn config.wsgi` cannot serve WebSockets.
web: uvicorn config.asgi:application --host 0.0.0.0 --port 8080
# Add these as separate DO components (Worker type), same repo/branch:
worker: celery -A config worker -l info
beat: celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
