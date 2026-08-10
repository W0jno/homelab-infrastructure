# Homelab Infrastructure

Infrastructure-as-code for a small Kubernetes cluster and a home-cinema host on Proxmox.

Terraform provisions Ubuntu VMs (k3s) and a Debian LXC (media). Ansible bootstraps [k3s](https://k3s.io/) and deploys a Docker Compose media stack. GitHub Actions validates Terraform and Ansible on every PR — apply stays local, because runners cannot reach the private LAN.

## Architecture

```text
                    ┌─────────────────────┐
                    │   GitHub Actions    │
                    │ fmt / validate /    │
                    │ lint / syntax-check │
                    └─────────┬───────────┘
                              │ PR checks only
                              ▼
┌──────────────┐     ┌────────────────┐     ┌──────────────────────────┐
│  Terraform   │────▶│    Proxmox     │────▶│  k3s VMs (Ubuntu)        │
│  bpg/proxmox │     │  template 9000 │     │  media LXC (Debian)      │
└──────────────┘     └────────────────┘     └────────────┬─────────────┘
                                                         │
                     ┌────────────────┐                  │
                     │    Ansible     │──────────────────┘
                     │ k3s + media    │
                     └────────────────┘
```

| Host | Role | IP | Notes |
|------|------|----|--------|
| `k3s-master` | control plane | `192.168.1.201` | Ubuntu VM |
| `k3s-worker-01` | agent | `192.168.1.202` | Ubuntu VM |
| `k3s-worker-02` | agent | `192.168.1.203` | Ubuntu VM |
| `media` | home cinema | `192.168.1.210` | Debian LXC + Docker; library on Proxmox `Media` → `/mnt/media` |

k3s and media are separate: cluster workloads stay on k3s; downloads/streaming run on the LXC.

## Tech stack

- **Proxmox VE** — hypervisor
- **Terraform** + `bpg/proxmox` — VM + LXC lifecycle, static IPs
- **Ansible** — OS baseline, k3s, Docker, Compose deploy
- **k3s** — lightweight Kubernetes
- **Docker Compose** — Jellyfin, qBittorrent, Sonarr, Bazarr
- **GitHub Actions** — CI validation (no remote apply)

## Repository layout

```text
.
├── terraform/environments/production/   # k3s VMs + media LXC
├── ansible/
│   ├── requirements.yml                 # Galaxy roles (geerlingguy.docker)
│   ├── playbooks/
│   │   ├── site.yml                     # bootstrap k3s
│   │   ├── destroy-k3s.yml              # uninstall k3s
│   │   └── media.yml                    # bootstrap media host
│   ├── inventory/
│   │   ├── production.ini
│   │   └── group_vars/                  # vars loaded with inventory
│   └── roles/
│       ├── common/                      # shared apt baseline
│       ├── k3s_common/                  # swap off, ip_forward, k3s script
│       ├── k3s_master/
│       ├── k3s_worker/
│       └── media_host/                  # dirs + copy compose + up
├── media/
│   └── docker-compose.yml               # home-cinema stack
├── k8s/manifests/                       # sample workloads
└── .github/workflows/                   # terraform + ansible CI
```

## Prerequisites

- Proxmox node with Ubuntu cloud-init template (`VMID 9000`) for k3s VMs
- Debian LXC template on Proxmox storage (e.g. `local:vztmpl/debian-…`) for media
- Proxmox storage for media library (e.g. `Media`) mounted into the LXC at `/mnt/media`
- Terraform >= 1.10
- Ansible + `ansible.posix` collection
- SSH key used by Cloud-Init / LXC `user_account`
- Proxmox API token (`user@realm!tokenid=secret`)

## Bootstrap

### 1. Configure secrets (local only)

Create `terraform/environments/production/production.auto.tfvars` (gitignored):

```hcl
proxmox_endpoint  = "your_proxmox_ip_address"
proxmox_api_token = "terraform@pve!token=..."
ssh_ubuntu_key    = "ssh-ed25519 AAAA... terraform-proxmox"

k3s_nodes = {
  # vm_id, name, ip, gateway, netmask, dns, memory, cores
}

media = {
  # vm_id, hostname, template_file_id, ip, gateway,
  # memory, cores, disk_size, media_datastore, media_size, media_mount_path
}
```

### 2. Provision infrastructure

```bash
cd terraform/environments/production
terraform init
terraform apply
terraform output
```

SSH checks:

```bash
# k3s (Ubuntu)
ssh -i ~/.ssh/proxmox_terraform ubuntu@192.168.1.201

# media LXC (SSH key lands on root)
ssh -i ~/.ssh/proxmox_terraform root@192.168.1.210
```

### 3. Bootstrap k3s

```bash
cd ../../../ansible
ansible-galaxy role install -r requirements.yml -p roles/galaxy
ansible k3s_cluster -m ping
ansible-playbook playbooks/site.yml
```

Ansible will:
1. harden nodes (`common` + `k3s_common`)
2. install k3s server on master
3. read the join token from master and join workers automatically
4. write a ready-to-use kubeconfig to `ansible/.kube/config` (API address rewritten from `127.0.0.1` to the master IP)

### 4. Verify cluster

```bash
export KUBECONFIG=$PWD/.kube/config
kubectl get nodes -o wide
```

Expected: three nodes in `Ready` state.

### 5. Bootstrap media host

```bash
cd ansible   # if not already there
ansible media -m ping
ansible-playbook playbooks/media.yml
```

This play:
1. runs `common` (apt baseline, including `gnupg` for Docker apt repos)
2. installs Docker via `geerlingguy.docker`
3. creates `/opt/media/...` and `/mnt/media/...` dirs
4. copies `media/docker-compose.yml` to the LXC and runs `docker compose up -d`

| Service | Port |
|---------|------|
| Jellyfin | `8096` |
| qBittorrent | `8080` |
| Sonarr | `8989` |
| Bazarr | `6767` |

Configs live under `/opt/media/config/`. Library and downloads use `/mnt/media` (TV → `/mnt/media/tv`, downloads → `/mnt/media/downloads`).

Remote access (Tailscale / existing home WireGuard) is separate from the Compose stack. A commercial VPN + Gluetun can be added later if you want torrent exit IP masking.

## CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `terraform.yml` | PR / push on `terraform/**` | `fmt`, `init -backend=false`, `validate` |
| `ansible.yml` | PR / push on `ansible/**` | `ansible-lint`, `--syntax-check` |

GitHub-hosted runners cannot reach `192.168.1.0/24`, so there is no remote `terraform apply` or `ansible-playbook` against the lab. Apply stays on a machine inside the LAN.

## Security notes

- `*.tfvars` and Terraform state are gitignored
- kubeconfig fetched by Ansible is written to `ansible/.kube/` (gitignored)
- Galaxy roles install under `ansible/roles/galaxy/` (gitignored) — use `requirements.yml`
- `media/.env` / `.env` are gitignored — keep VPN or app secrets out of git
- join token is read from the live master during the playbook run — no manual Vault copy after recreate
- API tokens and private keys never belong in git
