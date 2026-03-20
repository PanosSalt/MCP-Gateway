# Deployment Guide

This guide covers deploying MCP Gateway to production using Railway, Render, or a generic Docker host.

---

## Production Checklist

Before deploying, ensure these environment variables are set with secure, unique values:

| Variable | How to Generate |
|----------|-----------------|
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` (min 32 chars; longer keys add entropy) |
| `POSTGRES_PASSWORD` | `python3 -c "import secrets; print(secrets.token_urlsafe(24))"` |
| `BASE_URL` | Your public URL, e.g. `https://mcp-gateway.example.com` (no trailing slash) |
| `ANTHROPIC_API_KEY` | From [console.anthropic.com](https://console.anthropic.com/) (required for `/query/` endpoint) |

Optional but recommended for production:

| Variable | Notes |
|----------|-------|
| `CORS_ORIGINS` | Comma-separated allowed origins. Defaults to `BASE_URL` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | Default `15`. Shorter is more secure |
| `FILESYSTEM_ALLOWED_DIRS` | Leave empty to disable filesystem tools |

---

## Railway

[Railway](https://railway.app) supports Docker deployments with managed Postgres.

### 1. Create a project

1. Sign in to Railway and click **New Project**
2. Select **Deploy from GitHub repo** and connect your MCP Gateway repository
3. Railway auto-detects the `Dockerfile`

### 2. Add a Postgres database

1. In your project, click **New** and select **Database** then **PostgreSQL**
2. Railway provisions the database and exposes a `DATABASE_URL` variable automatically

### 3. Set environment variables

In the **api** service settings, go to **Variables** and add:

```
SECRET_KEY=<generated value>
ENCRYPTION_KEY=<generated 32-char value>
ANTHROPIC_API_KEY=sk-ant-...
BASE_URL=https://<your-railway-domain>.up.railway.app
```

Railway auto-injects `DATABASE_URL` from the linked Postgres addon. You do not need to set it manually.

### 4. Configure the health check

Under **Settings** > **Deploy**, set:
- **Health check path**: `/health`
- **Health check timeout**: `30s`

### 5. Run migrations

Open the Railway shell (service > **Settings** > **Railway Shell**) and run:

```bash
alembic upgrade head
```

Alternatively, the `entrypoint.sh` in the Docker image runs migrations on startup.

### 6. Verify

```bash
curl https://<your-railway-domain>.up.railway.app/health
# {"status": "ok"}
```

---

## Render

[Render](https://render.com) supports Docker web services with managed Postgres.

### 1. Create a Postgres database

1. In the Render dashboard, click **New** > **PostgreSQL**
2. Choose a plan and region
3. Note the **Internal Database URL** (starts with `postgresql://`)

### 2. Create a web service

1. Click **New** > **Web Service**
2. Connect your GitHub repository
3. Select **Docker** as the environment
4. Set the instance type (at least 512 MB RAM recommended)

### 3. Set environment variables

In the web service settings, add:

| Key | Value |
|-----|-------|
| `DATABASE_URL` | Internal Database URL from step 1 |
| `SECRET_KEY` | Generated value |
| `ENCRYPTION_KEY` | Generated 32-char value |
| `ANTHROPIC_API_KEY` | Your Anthropic key |
| `BASE_URL` | `https://<your-service>.onrender.com` |

### 4. Configure health check

Under **Settings**:
- **Health Check Path**: `/health`

### 5. Deploy

Render builds and deploys automatically on push. The `entrypoint.sh` runs `alembic upgrade head` on startup.

### 6. Verify

```bash
curl https://<your-service>.onrender.com/health
```

---

## Generic Docker / VPS

Deploy to any server with Docker installed (AWS EC2, DigitalOcean, Hetzner, etc.).

### 1. Clone and configure

```bash
git clone <repo-url> /opt/mcp-gateway
cd /opt/mcp-gateway
cp .env.example .env
```

Edit `.env` with production values:

```bash
POSTGRES_PASSWORD=<strong random password>
SECRET_KEY=<random 64-char string>
ENCRYPTION_KEY=<random string, min 32 chars — longer is better>
ANTHROPIC_API_KEY=sk-ant-...
BASE_URL=https://mcp.example.com
```

### 2. Start the stack

```bash
docker compose up -d --build
```

This starts:
- `api` on port 8000 (FastAPI + admin UI)
- `db` on port 5432 (PostgreSQL, internal)

### 3. Reverse proxy with Caddy (recommended)

Install [Caddy](https://caddyserver.com/) for automatic TLS:

```bash
# /etc/caddy/Caddyfile
mcp.example.com {
    reverse_proxy localhost:8000
}
```

```bash
sudo systemctl reload caddy
```

Caddy automatically provisions and renews Let's Encrypt certificates.

Alternatively, use nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name mcp.example.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE requires long-lived connections
    location /t/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
    }
}
```

### 4. Verify

```bash
curl https://mcp.example.com/health
# {"status": "ok"}
```

### 5. Register a tenant and connect Claude Desktop

```bash
curl -X POST https://mcp.example.com/tenants/ \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Org",
    "slug": "my-org",
    "admin_email": "admin@example.com",
    "admin_password": "SuperSecret123!"
  }'
```

Claude Desktop config:

```json
{
  "mcpServers": {
    "gateway": {
      "command": "npx",
      "args": ["mcp-remote", "https://mcp.example.com/t/my-org/mcp/sse"]
    }
  }
}
```

---

## Updating

Pull the latest code and rebuild:

```bash
cd /opt/mcp-gateway
git pull
docker compose up -d --build
```

The `entrypoint.sh` runs `alembic upgrade head` automatically on each container start, so database migrations are applied during deployment.

---

## Monitoring

### Health check

`GET /health` returns `{"status": "ok"}` when the database is reachable, `503` otherwise. Use this for load balancer health checks, Kubernetes probes, or uptime monitors.

### Logs

```bash
# API logs
docker compose logs -f api

# Database logs
docker compose logs -f db
```

The gateway suppresses repetitive `GET /health` entries from access logs to reduce noise.

### Audit trail

All significant events (logins, queries, config changes) are written to the `audit_logs` database table and accessible via `GET /audit-logs/` (admin only).
