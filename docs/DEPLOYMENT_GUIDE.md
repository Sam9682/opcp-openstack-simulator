# Deployment Guide

## Prerequisites

- Python 3.9 or higher
- Docker and Docker Compose (for containerized deployment)
- nginx (optional, for standalone production deployment)

## Deployment Options

|        Method      |        Best For       |           Port         |
|--------------------|-----------------------|------------------------|
| Docker Compose     | Production, team use  | 8080 (web), 5000 (API) |
| Development server | Local development     | 8000                   |
| Gunicorn + nginx   | Standalone production | 5000                   |

---

## Option 1: Docker Compose (Recommended)

The simplest way to run the simulator. Two containers: the app (gunicorn) and nginx (reverse proxy).

### Start

```bash
# Clone and enter the project
git clone <repository-url>
cd opcp-openstack-simulator

# Build and start
docker compose up -d
```

### Verify

```bash
# Check containers are running
docker compose ps

# Test the web page (browser)
curl http://localhost:8080/

# Test the API
curl http://localhost:5000/identity/v3/
```

### Ports

| Port |     Service    |         Description            |
|------|----------------|--------------------------------|
| 8080 | nginx (HTTP)   | Web page showing documentation |
| 5000 | app (gunicorn) | OpenStack API endpoints        |

### Environment Variables

You can customize ports via environment variables:

```bash
HTTP_PORT=6000 WEB_PORT=9090 docker compose up -d
```

|  Variable   | Default |         Description       |
|-------------|---------|---------------------------|
| `HTTP_PORT` | 5000    | API port (direct to app)  |
| `WEB_PORT`  | 8080    | Web page port (via nginx) |

### Logs

```bash
# All services
docker compose logs -f

# Just the app
docker compose logs -f app

# Just nginx
docker compose logs -f nginx
```

### Stop

```bash
docker compose down
```

### Rebuild (after code changes)

```bash
docker compose down
docker compose build
docker compose up -d
```

---

## Option 2: Development Server

For local development and debugging. Runs Flask's built-in server with hot reload.

### Setup

```bash
# Install the package in development mode
pip install -e ".[dev]"
```

### Start

```bash
# Using the start script
./deploy/start.sh --dev

# Or directly
python -m openstack_simulator.api.wsgi
```

The server runs on `http://127.0.0.1:8000`.

### Configure CLI

When using the dev server directly (no nginx), point the CLI to port 8000:

```bash
export OS_AUTH_URL=http://localhost:8000/identity/v3
```

---

## Option 3: Gunicorn + nginx (Standalone)

For production deployment without Docker.

### Install

```bash
pip install -e .
```

### Start gunicorn

```bash
gunicorn openstack_simulator.api.wsgi:app \
    --bind 127.0.0.1:8000 \
    --workers 1 \
    --timeout 120 \
    --access-logfile - \
    --error-logfile -
```

> **Important:** Use exactly 1 worker. The simulator stores state in memory — multiple workers would each have separate state.

### Configure nginx

```bash
# Copy the nginx config
sudo cp deploy/nginx/openstack-simulator.conf /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/openstack-simulator.conf /etc/nginx/sites-enabled/

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

The nginx config proxies port 5000 to gunicorn on port 8000.

---

## OpenStack CLI Configuration

After the simulator is running, configure the OpenStack CLI to connect to it.

### Using clouds.yaml

```bash
mkdir -p ~/.config/openstack
cp deploy/clouds.yaml ~/.config/openstack/clouds.yaml
export OS_CLOUD=simulator
```

### Using Environment Variables

```bash
export OS_AUTH_URL=http://localhost:5000/identity/v3
export OS_APPLICATION_CREDENTIAL_ID=simulator-app-credential
export OS_APPLICATION_CREDENTIAL_SECRET=simulator-secret
export OS_REGION_NAME=RegionOne
export OS_INTERFACE=public
export OS_IDENTITY_API_VERSION=3
export OS_AUTH_TYPE=v3applicationcredential
```

### Verify Connectivity

```bash
openstack token issue
openstack server list
```

---

## Configuration

The simulator's default configuration can be overridden. When using Docker, you can set these via environment variables in a future version. Currently, defaults are:

| Setting | Default | Description |
|---------|---------|-------------|
| `default_flavor` | m1.small | Default flavor for instances |
| `default_image` | ubuntu-22.04 | Default image for instances |
| `session_timeout` | 120 | Token validity in minutes |
| `max_instances` | 3 | Maximum compute instances |
| `max_networks` | 2 | Maximum networks |
| `max_volumes` | 3 | Maximum volumes |
| `max_security_groups` | 5 | Maximum security groups |

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker compose logs app

# Common issue: port already in use
docker compose down
lsof -i :5000  # find what's using the port
```

### 401 Unauthorized errors

- Ensure you're using the correct `auth_url` (matches the running port)
- Check that `OS_AUTH_TYPE=v3applicationcredential` is set
- Verify credentials are non-empty strings

### Token works for one request but not the next

- This happens with multiple gunicorn workers (each has separate memory)
- Solution: ensure `--workers 1` in the gunicorn command (already set in Dockerfile)

### nginx returns 502 Bad Gateway

- The app container hasn't started yet — wait a few seconds
- Check `docker compose logs app` for startup errors

### State resets on restart

- This is by design — all state is in-memory
- Restarting the container clears all resources
- Re-create resources after restart
