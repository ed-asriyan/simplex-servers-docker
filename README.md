# SimpleX Servers - Env-Driven Docker Setup
Clean, env-vars configurable Docker deployment for the [SimpleX SMP and XFTP Servers](https://github.com/simplex-chat/simplexmq).

Forget about manual `.ini` edits and mounting config folders. This setup dynamically generates the entire server configuration from a single `.env` file and automatically provisions Let's Encrypt TLS certificates using Caddy.

## Prerequisites
Before deploying, ensure your server meets the following requirements:

**Mandatory:**
* **Docker and Docker Compose** installed.
* A **Public IP address**.
* **Port `80` must be available** (open in the firewall and not occupied by other processes) for Caddy to solve HTTP-01 challenges.
* **Port `443`** (or your custom defined port) must be available for secure client-server communication.

**Optional but Recommended:**
* A **Domain Name (DNS A-record)** pointing to your server's public IP.

## Repository Structure
*   `/smp` — Deployment configuration for the SimpleX SMP Server.
*   `/xftp` — Deployment configuration for the SimpleX XFTP Server.

> **⚠️ Important Note on Co-hosting:** 
> If you intend to run *both* the SMP and XFTP servers on the exact same host machine/IP, running both `docker-compose.yml` files simultaneously will cause port conflicts (both Caddy instances will attempt to bind to port `80` for ACME challenges). You will need to either utilize a single external reverse proxy (like Nginx/Traefik) or merge their configurations to share a single Caddy instance.

---

## 🚀 Quick Start: SMP Server
1. Download the deployment files:
   ```bash
   mkdir smp && cd smp
   curl -O https://raw.githubusercontent.com/ed-asriyan/simplex-servers-docker/master/smp/docker-compose.yml
   curl -sSL https://raw.githubusercontent.com/ed-asriyan/simplex-servers-docker/master/smp/.env > .env
   ```
2. Configure the environment variables (uncommented lines are mandatory settings that must be configured by the user, commented lines are optional)
   ```bash
   vim .env
   ```
3. Start the server:
   ```bash
   docker compose up -d
   ```
4. Print the XFTP address:
   ```bash
   docker compose logs | grep "Server address:"
   ```
5. Add the address to your SimpleX Chat client.
6. _(optional)_ Add the server to the [Unofficial SimpleX Catalog](https://simplex-directory.asriyan.me).

**Applying Changes after startup**
If you want to change any setting, simply modify the .env file and run:
```bash
docker compose up -d
```

---

## 🚀 Quick Start: XFTP Server
1. Download the deployment files:
   ```bash
   mkdir xftp && cd xftp
   curl -O https://raw.githubusercontent.com/ed-asriyan/simplex-servers-docker/master/xftp/docker-compose.yml
   curl -sSL https://raw.githubusercontent.com/ed-asriyan/simplex-servers-docker/master/xftp/.env > .env
   ```
2. Configure the environment variables (uncommented lines are mandatory settings that must be configured by the user, commented lines are optional)
   ```bash
   vim .env
   ```
3. Start the server:
   ```bash
   docker compose up -d
   ```
4. Print the XFTP address:
   ```bash
   docker compose logs | grep "Server address:"
   ```
5. Add the address to your SimpleX Chat client.
6. _(optional)_ Add the server to the [Unofficial SimpleX Catalog](https://simplex-directory.asriyan.me).

**Applying Changes after startup**
If you want to change any setting, simply modify the .env file and run:
```bash
docker compose up -d
```

---

## 💾 State Persistence
Databases, logs, server keys, and uploaded files (for XFTP) are safely persisted in local directories (`./smp_state`, `./xftp_state`, etc.) relative to the `docker-compose.yml` files.

## 🚚 Migrating Data to Another Server
To migrate your server to a new host, you simply need to copy your deployment folder containing the `.env` file and the state directories (`smp_state`/`xftp_state` and Caddy data) to the new server.

1. Stop the server on the old host:
   ```bash
   docker compose down
   ```
2. Copy the entire deployment folder (which includes `docker-compose.yml`, `.env`, and the state directories) to the new server. You can use `rsync` or `scp`. For example:
   ```bash
   scp -r user@old-server:/path/to/deployment/folder user@new-server:/path/to/destination/
   ```
3. On the new server, navigate into the directory and start the server:
   ```bash
   cd /path/to/destination/folder
   docker compose up -d
   ```
