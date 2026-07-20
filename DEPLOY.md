# Deploying Engram on Alibaba Cloud ECS

This is the full, copy-pasteable path from a fresh Alibaba Cloud account to a
running Engram stack (Postgres + FastAPI backend + nginx-served React frontend)
reachable over the public internet, plus the Devpost "Proof of Deployment"
screenshot step.

The whole app runs from **one** `docker compose up`. You need exactly two
secrets on the server: a **DashScope (Model Studio) API key** and a
**`DATABASE_URL`**.

All commands below assume a normal sudo-capable user (e.g. `ecs-user` or
`ubuntu`) — you do **not** need to be root or run `sudo -i`.

> Region note: use **Singapore** and the **intl** Model Studio endpoint. The
> backend defaults to `https://dashscope-intl.aliyuncs.com/compatible-mode/v1`,
> which is the hackathon-recognized endpoint. A Singapore key will not work
> against the Beijing endpoint and vice-versa.

---

## 1. Provision an ECS instance (Console)

In the Alibaba Cloud console → **Elastic Compute Service (ECS)** → **Instances**
→ **Create Instance**:

- **Region:** Singapore (`ap-southeast-1`)
- **Instance type:** any 2 vCPU / 4 GiB (e.g. `ecs.e-c1m2.large` or a burstable
  `ecs.t6` equivalent)
- **Image:** Ubuntu 24.04 LTS (64-bit x86_64)
- **Storage:** 40 GiB system disk (ESSD) is plenty
- **Public IP:** enable **Assign Public IPv4** (or bind an EIP afterward)
- **Bandwidth:** Pay-by-traffic, a few Mbps is fine
- **Key pair / password:** create or select an SSH key pair (recommended) or set
  a root password

### Security group (inbound rules)

Open these ports to `0.0.0.0/0` (IPv4) on the instance's security group:

| Port | Protocol | Purpose                          |
|------|----------|----------------------------------|
| 22   | TCP      | SSH                              |
| 80   | TCP      | Frontend (nginx) / API / voice   |
| 443  | TCP      | HTTPS (optional, if you add TLS) |

Note the instance's **public IP** — referred to below as `SERVER_IP`.

---

## 2. SSH into the instance

```bash
# Alibaba Cloud Ubuntu images typically use ecs-user (or ubuntu)
ssh -i /path/to/your.pem ecs-user@SERVER_IP
```

---

## 3. Install Docker + the Compose plugin

```bash
# Refresh apt and install prerequisites
sudo apt-get update
sudo apt-get install -y ca-certificates curl git

# Add Docker's official APT repository
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine + Compose v2 plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Let your user run docker without sudo (log out/in, or newgrp, for it to apply)
sudo usermod -aG docker "$USER"
newgrp docker

# Verify
docker --version
docker compose version
```

> If a slow/blocked pull from Docker Hub is a problem in your region, configure
> an Alibaba Cloud image accelerator (Container Registry → Image Accelerator)
> by writing the mirror into `/etc/docker/daemon.json`, then restart Docker:
>
> ```bash
> echo '{"registry-mirrors": ["<your-accelerator-url>"]}' | sudo tee /etc/docker/daemon.json
> sudo systemctl restart docker
> ```

---

## 4. Clone the repository

```bash
sudo mkdir -p /opt
sudo git clone https://github.com/yfshaikh/qwen /opt/qwen
sudo chown -R "$USER:$USER" /opt/qwen
cd /opt/qwen
```

---

## 5. Create the `.env`

The stack reads two variables. Create `/opt/qwen/.env`:

```bash
cat > .env <<'EOF'
# --- Required: Alibaba Cloud Model Studio (DashScope), Singapore/intl key ---
DASHSCOPE_API_KEY=sk-your-singapore-model-studio-key

# --- Database ---
# Using the bundled Postgres service (default). Point at the internal Docker
# service name "db" — NOT localhost (localhost inside the backend container is
# the container itself, which has no Postgres).
DATABASE_URL=postgresql://engram:engram@db:5432/engram
EOF
```

Where to get `DASHSCOPE_API_KEY`: Alibaba Cloud console → **Model Studio**
(Bailian) in the **Singapore** region → **API Keys** → create/copy a key.

> **Important — `DATABASE_URL` and the bundled Postgres.** `docker compose`
> auto-loads this `.env` for variable substitution. For the bundled database the
> value **must** use the internal service host `db` (as above). If you leave
> `DATABASE_URL` unset entirely, the backend falls back to exactly this DSN, so
> both work — but do **not** set it to `localhost`/`127.0.0.1`, or the backend
> container will fail to reach Postgres with `Connection refused`.

---

## 6. Bring the stack up

```bash
docker compose up -d --build
```

This builds the backend and frontend images, starts Postgres (which
auto-applies everything in `migrations/` on first init — the schema and
`vector`/`pgcrypto` extensions), waits for it to be healthy, then starts the
backend and the nginx frontend.

Check status and logs:

```bash
docker compose ps
docker compose logs -f            # Ctrl-C to stop following
docker compose logs -f backend    # just the backend
```

---

## 7. Verify

On the server:

```bash
# Backend health — proves the API is up AND connected to Postgres (db:true)
curl http://localhost/health
# -> {"status":"ok","db":true}

# Frontend SPA is being served by nginx
curl -s http://localhost/ | grep -i "<title>"
# -> <title>Engram Console</title>
```

From your laptop / browser:

```
http://SERVER_IP/            # the Engram Console UI
http://SERVER_IP/health      # {"status":"ok","db":true}
```

nginx serves the SPA on port 80 and reverse-proxies the API paths
(`/chat /graph /consolidate /audit /health /sessions /memory /eval /insights`)
and the `/voice` WebSocket to the backend, so the whole app is same-origin on
port 80 — no separate backend port needs to be exposed publicly.

---

## 8. Devpost "Proof of Deployment" — Workbench screenshot

For the Devpost submission, capture proof that the app is live on Alibaba Cloud:

1. Open a browser to `http://SERVER_IP/` and confirm the **Engram Console** loads
   (graph view + chat/voice panel).
2. Open the **Alibaba Cloud console → Model Studio (Bailian) → Workbench** in the
   **Singapore** region. Exercise the app (send a chat / run a voice turn) so
   real requests hit your DashScope key, then open Model Studio's usage/logs so
   the calls are visible.
3. Take a screenshot showing **both** the running app URL (`http://SERVER_IP/…`
   visible in the address bar) **and** the Alibaba Cloud Model Studio Workbench /
   usage in the same or adjacent frames — this is the "Proof of Deployment" the
   Devpost submission asks for.
4. (Recommended) Also screenshot the ECS **Instances** list showing the running
   instance and its public IP in the Singapore region.

---

## Alternative: use PolarDB instead of the bundled Postgres

To use **PolarDB for PostgreSQL** (managed, with pgvector) instead of the
Postgres container:

1. Create a **PolarDB for PostgreSQL** cluster in the **Singapore** region.
   Create a database and an account, and add the ECS instance's IP (or VPC) to
   the cluster's whitelist so it can connect.

2. Enable pgvector and apply the schema. Connect with `psql` from the ECS box
   (install once with `sudo apt-get install -y postgresql-client`), using the
   PolarDB primary endpoint:

   ```bash
   export PGURL="postgresql://<user>:<password>@<polardb-endpoint>:5432/<db>"

   # pgvector must exist before the schema (engram_nodes uses vector(1024))
   psql "$PGURL" -c "CREATE EXTENSION IF NOT EXISTS vector;"
   psql "$PGURL" -c "CREATE EXTENSION IF NOT EXISTS pgcrypto;"

   # Apply the consolidated schema (idempotent; equivalent to all numbered
   # migrations). Run from the repo root so the path resolves.
   cd /opt/qwen
   psql "$PGURL" -f migrations/schema.sql
   ```

3. Point the backend at PolarDB in `/opt/qwen/.env` and **do not** run the
   bundled `db` service:

   ```bash
   # .env
   DASHSCOPE_API_KEY=sk-your-singapore-model-studio-key
   DATABASE_URL=postgresql://<user>:<password>@<polardb-endpoint>:5432/<db>
   ```

   ```bash
   # Bring up only the backend + frontend (skip the local Postgres container)
   docker compose up -d --build backend frontend
   ```

   The backend will connect to PolarDB. Verify the same way:
   `curl http://localhost/health` → `{"status":"ok","db":true}`.

> If your PolarDB endpoint requires TLS, append the appropriate sslmode to the
> DSN, e.g. `...:5432/<db>?sslmode=require`.

---

## Operations: logs, restart, update, teardown

```bash
cd /opt/qwen

# Logs
docker compose logs -f              # all services
docker compose logs -f backend      # one service
docker compose logs --tail=100 backend

# Restart a service (e.g. after changing .env)
docker compose restart backend
docker compose up -d                # re-reads .env, recreates changed services

# Pull latest code and rebuild
git pull
docker compose up -d --build

# Stop the stack (keep the database volume / data)
docker compose down

# Stop AND delete the database volume (wipes all data)
docker compose down -v

# Full status
docker compose ps
```

### Optional: HTTPS on 443

The security group already allows 443. To serve TLS, put a terminating proxy in
front (e.g. Caddy or an nginx with certbot, or an Alibaba Cloud SLB/ALB with a
certificate) that forwards to the frontend container on port 80. The bundled
nginx config listens on 80 and is HTTP-only by design.
