# Setup Guide

To successfully run QuadletManager, your target servers need to allow the agent (SSH User) to run `systemctl` commands and read/write files in `/etc/containers/systemd/` without a password prompt.

> [!IMPORTANT]
> **Managing the Local Host (Loopback Connection):**
> If you are running QuadletManager inside a container (using Podman/Docker) and want to manage the host machine it is running on:
> - Do not use `localhost` or `127.0.0.1` as the server IP, as that refers to the container itself.
> - For **Podman**, use **`host.containers.internal`** as the IP/hostname in the settings panel.
> - For **Docker**, use **`host.docker.internal`** (you may need to add `extra_hosts: ["host.docker.internal:host-gateway"]` to your `docker-compose.yml` or container configuration flags on Linux).
> - Make sure the host's SSH service is running, and your public SSH key is added to the host's `authorized_keys` file.

## 1. Create a Dedicated User (Recommended)
On your target server:
```bash
sudo useradd -m -s /bin/bash quadlet-agent
```
Add your QuadletManager's public SSH key to `/home/quadlet-agent/.ssh/authorized_keys`.

## 2. Rootless Quadlets (No Sudo)
For user-level quadlets, no special permissions are required. The agent will read/write dynamically to:
`~/.config/containers/systemd/`

## 3. Global Quadlets (Sudoers Setup)
To manage system-wide Quadlets, you must grant the agent (`quadlet-agent`) passwordless sudo access strictly for `systemd` and `tee` interactions.

Create a file on the target server at `/etc/sudoers.d/quadlet-manager`:

```bash
# Allow agent to execute daemon-reload and interact with services
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/systemctl daemon-reload
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/systemctl start *
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop *
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart *
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/systemctl status *
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/journalctl -u *

# Allow agent to write files exclusively into the quadlet directory via tee
quadlet-agent ALL=(ALL) NOPASSWD: /usr/bin/tee /etc/containers/systemd/*
```

## 4. Installation
Before running the application, you need to set up a Python virtual environment and install the required dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## 5. Setting the Master Key
On your host machine, you **must** export the Master Key or set it in your `config.yaml` before booting the FastAPI app to decrypt DB SSH keys correctly.

```bash
export QUADLET_MASTER_KEY="a_secure_256_bit_hex_string_here"
uvicorn main:app --host 0.0.0.0 --port 8000
```

## 6. Application Login
Upon first startup, the database is seeded with two default users:
- **Username:** `admin` | **Password:** `admin` (Role: Editor)
- **Username:** `viewer` | **Password:** `viewer` (Role: Viewer)

You will be prompted via HTTP Basic Authentication when loading the dashboard. Please change these passwords if deploying in production.
