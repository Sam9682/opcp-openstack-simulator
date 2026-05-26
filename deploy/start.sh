#!/usr/bin/env bash
# Start the OpenStack Simulator API server.
#
# Usage:
#   ./deploy/start.sh          # Start with gunicorn (production)
#   ./deploy/start.sh --dev    # Start with Flask dev server (debug mode)
#
# Prerequisites:
#   pip install -e .
#   (optional) nginx configured with deploy/nginx/openstack-simulator.conf

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

if [ "$1" = "--dev" ]; then
    echo "Starting OpenStack Simulator in development mode on http://127.0.0.1:8000"
    echo "Use clouds.yaml with auth_url: http://localhost:8000/identity/v3"
    python -m openstack_simulator.api.wsgi
else
    echo "Starting OpenStack Simulator with gunicorn on http://127.0.0.1:8000"
    echo ""
    echo "If nginx is configured, the API is available at http://localhost:5000"
    echo "Use clouds.yaml with auth_url: http://localhost:5000/identity/v3"
    echo ""
    gunicorn openstack_simulator.api.wsgi:app \
        --bind 127.0.0.1:8000 \
        --workers 2 \
        --timeout 120 \
        --access-logfile - \
        --error-logfile -
fi
