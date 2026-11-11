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
4. Print the server addresses (see [Server Addresses](#-server-addresses)):
   ```bash
   cat addresses.txt
   ```
5. Add the `smp` address to your SimpleX Chat client.
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
4. Print the server addresses (see [Server Addresses](#-server-addresses)):
   ```bash
   cat addresses.txt
   ```
5. Add the `xftp` address to your SimpleX Chat client.
6. _(optional)_ Add the server to the [Unofficial SimpleX Catalog](https://simplex-directory.asriyan.me).

**Applying Changes after startup**
If you want to change any setting, simply modify the .env file and run:
```bash
docker compose up -d
```

---

## 📇 Server Addresses
On every start the `addresses` service prints ready-to-use addresses, one per line, and saves them to `./addresses.txt`:
```
SIMPLEX_ADDRESS <network> <type> <address>
```
* `<network>` — `clearnet` or `yggdrasil` (the latter only with `docker-compose.clearnet-yggdrasil.yml`).
* `<type>` — `smp` / `xftp` for the server address to add to SimpleX Chat, `info` for the server information web page.

Example:
```
SIMPLEX_ADDRESS clearnet smp smp://<fingerprint>@smp.example.com
SIMPLEX_ADDRESS clearnet info https://smp.example.com/
SIMPLEX_ADDRESS yggdrasil smp smp://<fingerprint>@[200:1234:5678::1]
SIMPLEX_ADDRESS yggdrasil info http://[200:1234:5678::1]/
```

The format is stable and meant for scripts, e.g.:
```bash
docker compose logs --no-log-prefix addresses | grep '^SIMPLEX_ADDRESS ' | awk '$2 == "yggdrasil" && $3 == "smp" { print $4 }'
```

## 🌳 Yggdrasil
`docker-compose.clearnet-yggdrasil.yml` additionally exposes the server on its [Yggdrasil](https://yggdrasil-network.github.io) address. It requires two more variables in `.env`:
* `YGG_PRIV_KEY` — node private key (hex). The Yggdrasil address is derived from it, so keep it stable. Generate one with `yggdrasil -genconf -json` and take `PrivateKey`.
* `YGG_PEERS` — space-separated list of peers, e.g. `tls://ygg.example.net:443`.

```bash
docker compose -f docker-compose.clearnet-yggdrasil.yml up -d
```

## 🔐 Custom ACME CA
Certificates are issued by Let's Encrypt by default. To use another ACME CA (Let's Encrypt staging, ZeroSSL, a private CA, ...), set its directory URL in `.env`:
```
ACME_CA=https://acme-staging-v02.api.letsencrypt.org/directory
```
The Caddy configuration is generated from `.env` on every `docker compose up`, so changes to `SMP_ADDR`/`XFTP_ADDR`, ports or `ACME_CA` are applied automatically.

> **Upgrading:** earlier versions generated `caddy_conf/Caddyfile` once and kept it. That directory is no longer used and can be deleted; manual edits to it are not carried over.

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

## 🧪 Tests
`.github/workflows/e2e.yml` runs `tests/e2e.py` on every push and pull request for each compose file (`smp`/`xftp` × `clearnet`/`yggdrasil`). The test:
1. brings the deployment up with [Pebble](https://github.com/letsencrypt/pebble) as the ACME CA (`tests/compose.ci.yml`) and, for the Yggdrasil variant, a local Yggdrasil node peered with the server's node;
2. reads the `SIMPLEX_ADDRESS` lines;
3. runs `/_server test 1 <address>` in the [SimpleX Chat CLI](https://github.com/simplex-chat/simplex-chat/blob/stable/docs/CLI.md) for every server address and published port, and opens every `info` page in headless Chromium.

Logs and screenshots are uploaded as workflow artifacts. To run locally (needs Docker, IPv6, the `simplex-chat` CLI, Python Playwright, and `yggdrasil` + root for the Yggdrasil variant):
```bash
echo "127.0.0.1 smp.test xftp.test" | sudo tee -a /etc/hosts
python tests/e2e.py --server smp --variant clearnet
```
