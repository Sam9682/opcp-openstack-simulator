"""WSGI entry point for the OpenStack Simulator API.

Usage with gunicorn:
    gunicorn openstack_simulator.api.wsgi:app -b 127.0.0.1:8000

Usage with Flask dev server:
    python -m openstack_simulator.api.wsgi
"""

from openstack_simulator.api.app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8000, debug=True)
