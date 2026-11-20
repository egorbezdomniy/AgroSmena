"""Explicit WSGI baseline for Linux hosting; see docs/scaling-stage-1.md."""
import os
from crmserver.env import env_int

# Keep the platform's launch configuration unless adopting this file explicitly.
bind = os.environ.get('GUNICORN_BIND', '127.0.0.1:8000')
# One process avoids splitting the existing in-memory login throttle across workers.
# This is a conservative starting point, not a measured capacity recommendation.
workers = env_int('WEB_CONCURRENCY', 1, minimum=1)
worker_class = 'sync'
timeout = env_int('GUNICORN_TIMEOUT', 30, minimum=1)
accesslog = None  # Default access logs contain raw URLs/query strings.
errorlog = '-'
capture_output = True
# Django handles proxy scheme recognition explicitly; no independent header trust here.
forwarded_allow_ips = ''
