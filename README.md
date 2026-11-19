# Homelab Infrastructure

Infrastructure-as-code for a small Kubernetes cluster, a self-hosted photo library (Immich) and a start-page dashboard (Homepage) on a two-node Proxmox cluster.

Terraform provisions Ubuntu VMs (k3s) and a Debian LXC (Homepage) on node `pve`, and a Debian LXC (Immich) on node `pve2`. Ansible bootstraps [k3s](https://k3s.io/) and deploys [Immich](https://immich.app/) and [Homepage](https://gethomepage.dev) with Docker Compose. GitHub Actions validates Terraform, Ansible and Kubernetes manifests on every PR — apply stays local, because runners cannot reach the private LAN.

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
│  bpg/proxmox │     │  pve + pve2    │     │  Immich LXC (Debian)     │
└──────────────┘     └────────────────┘     │  Homepage LXC (Debian)   │
                                            └────────────┬─────────────┘
                     ┌────────────────┐                  │
                     │    Ansible     │──────────────────┘
                     │ k3s + immich + │
                     │ homepage       │
                     └────────────────┘
```

| Host | Role | IP | Notes | In code |
|------|------|----|-------|---------|
| `pve` | Proxmox node (ProDesk 1) | `192.168.1.122` | k3s VMs, Homepage + service LXCs; UI `https://proxmox.home` | — |
| `pve2` | Proxmox node (ProDesk 2) | `192.168.1.123` | Immich LXC | — |
| `k3s-master` | control plane | `192.168.1.201` | Ubuntu VM 9001 on `pve` | Terraform + Ansible |
| `k3s-worker-01` | agent | `192.168.1.202` | Ubuntu VM 9002 on `pve` | Terraform + Ansible |
| `k3s-worker-02` | agent | `192.168.1.203` | Ubuntu VM 9003 on `pve` | Terraform + Ansible |
| `homepage` | dashboard ([Homepage](https://gethomepage.dev)) | `192.168.1.204` | LXC 107 + Docker on `pve`, `http://192.168.1.204:3000`; shows only the services described in the thesis | Terraform + Ansible |
| `immich` | photo library | `192.168.1.168` | LXC 8100 + Docker on `pve2`, `:2283`; photos on a separate `local-lvm` volume → `/mnt/photos` | Terraform + Ansible |
| `npm-proxy` | Nginx Proxy Manager | `192.168.1.30` | LXC 104 on `pve`, admin `:81` / `http://proxy.home` | Terraform (LXC only) |
| `pihole-backup` | DNS (backup) | `192.168.1.28` | LXC 100 on `pve` | Terraform (LXC only) |
| `home-tools-1` | Overleaf | `192.168.1.101` | LXC 102 on `pve`, `:8080` | Terraform (LXC only) |
| `vaultwarden` | password manager | `192.168.1.40` | LXC 105 on `pve` | Terraform (LXC only) |
| `home-obsidian-db-1` | Obsidian sync DB (CouchDB) | DHCP | LXC 106 on `pve`, `:5984` | Terraform (LXC only) |
| Pi-hole | primary DNS, local `.home` zone | `192.168.1.27` | Raspberry Pi | — |

k3s workloads: portfolio (`portfolio.fwojno.com` via Cloudflare Tunnel, LAN NodePort `30080`), `cloudflared` (2 replicas), `kube-prometheus-stack` (Prometheus 7d retention, Grafana on LAN NodePort `30300`).

The five service LXCs (100–106) were created by hand and later imported into Terraform (`services.tf`), so their Proxmox definition (CPU, RAM, disk, network) is in code with `prevent_destroy`. What runs inside them is not managed by Ansible yet. Proxmox, the Raspberry Pi and the Nginx Proxy Manager proxy hosts are configured outside this repo.

k3s and Immich are separate: cluster workloads stay on k3s (`pve`); the photo library runs in its own LXC on a different node (`pve2`). k3s runs without Traefik (disabled in `/etc/rancher/k3s/config.yaml`), since nothing uses an Ingress.

## Tech stack

- **Proxmox VE** — hypervisor
- **Terraform** + `bpg/proxmox` — VM + LXC lifecycle, static IPs
- **Ansible** — OS baseline, k3s, Docker, Compose deploy
- **k3s** — lightweight Kubernetes
- **Docker Compose** — Immich (server, machine learning, Valkey, Postgres), Homepage
- **Helm** — `kube-prometheus-stack` (Prometheus + Grafana)
- **Cloudflare Tunnel** — public access to the portfolio without open ports
- **GitHub Actions** — CI validation (no remote apply)

## Repository layout

```text
.
├── terraform/environments/production/   # k3s VMs, template 9000, Immich, Homepage + service LXCs
├── ansible/
│   ├── requirements.yml                 # Galaxy roles (geerlingguy.docker)
│   ├── playbooks/
│   │   ├── site.yml                     # bootstrap k3s
│   │   ├── destroy-k3s.yml              # uninstall k3s
│   │   ├── immich.yml                   # bootstrap Immich host
│   │   └── homepage.yml                 # bootstrap Homepage dashboard
│   ├── inventory/
│   │   ├── production.ini
│   │   └── group_vars/                  # vars loaded with inventory
│   └── roles/
│       ├── common/                      # shared apt baseline
│       ├── k3s_common/                  # swap off, ip_forward, k3s script
│       ├── k3s_master/
│       ├── k3s_worker/
│       ├── immich/                      # dirs + compose + .env + up
│       └── homepage/                    # dashboard: compose + config from homepage_services
├── immich/
│   ├── docker-compose.yml               # official Immich stack
│   └── .env.example                     # template; real .env is rendered by Ansible
├── k8s/
│   ├── manifests/                       # portfolio + cloudflared
│   └── monitoring/                      # kube-prometheus-stack values + Grafana dashboard
├── tests/                               # static (CI) + live pytest suites
└── .github/
    ├── workflows/                       # terraform, ansible, manifests, tests, security
    └── scripts/check_helm_values.py     # fails on unknown Helm values keys
```

## Prerequisites

- Proxmox cluster with nodes `pve` and `pve2`
- Terraform downloads the Ubuntu cloud image and builds template `9000` (`template.tf`), and downloads the Debian LXC template to `pve2`
- The Homepage and service LXCs on `pve` use `local:vztmpl/debian-13-standard_13.1-2_amd64.tar.zst`, which must already be on `pve` (`pveam download local debian-13-standard_13.1-2_amd64.tar.zst`)
- Terraform >= 1.10
- Ansible (Galaxy roles and collections from `ansible/requirements.yml`)
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

immich = {
  # vm_id, node_name, hostname, template_url, ip, gateway, memory, swap,
  # cores, disk_size, photos_datastore, photos_size, photos_path
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

# Immich and Homepage LXCs (SSH key lands on root)
ssh -i ~/.ssh/proxmox_terraform root@192.168.1.168
ssh -i ~/.ssh/proxmox_terraform root@192.168.1.204
```

### 3. Bootstrap k3s

```bash
cd ../../../ansible
ansible-galaxy role install -r requirements.yml -p roles/galaxy
ansible-galaxy collection install -r requirements.yml -p collections
ansible k3s_cluster -m ping
ansible-playbook playbooks/site.yml
```

Ansible will:
1. harden nodes (`common` + `k3s_common`)
2. write `/etc/rancher/k3s/config.yaml` (disables Traefik) and install k3s server on master; changing `k3s_version` upgrades in place (workers one at a time)
3. read the join token from master and join workers automatically
4. write a ready-to-use kubeconfig to `ansible/.kube/config` (API address rewritten from `127.0.0.1` to the master IP)

### 4. Verify cluster

```bash
export KUBECONFIG=$PWD/.kube/config
kubectl get nodes -o wide
```

### 5. Bootstrap Immich host

```bash
cd ansible   # if not already there
ansible immich -m ping
ansible-playbook playbooks/immich.yml
```

This play:
1. runs `common` (apt baseline, including `gnupg` for Docker apt repos)
2. installs Docker via `geerlingguy.docker`
3. creates `/opt/immich` and `/mnt/photos/library`
4. copies `immich/docker-compose.yml`, renders `/opt/immich/.env` (mode `0600`) and runs `docker compose up -d`

Immich UI: `http://192.168.1.168:2283` (the first account you create becomes the admin). The version is pinned with `immich_version` in `ansible/roles/immich/defaults/main.yml`.

The Postgres password is generated on first run by the Ansible `password` lookup and kept in `ansible/credentials/immich_db_password` (gitignored). Back up that file together with the photos.

Photos live in `/mnt/photos/library` on a separate volume; the database lives in `/opt/immich/postgres` on the container rootfs. The container has `prevent_destroy`.

### 6. Bootstrap Homepage dashboard

```bash
cd ansible   # if not already there
ansible-playbook playbooks/homepage.yml
```

Dashboard: `http://192.168.1.204:3000`. The tiles are rendered from `homepage_services` in `ansible/roles/homepage/defaults/main.yml` (single source of truth). Only services described in the thesis are listed (enforced by a static test). Tiles link through NPM/DNS names where one exists (`proxmox.home`, `proxy.home`, `portfolio.fwojno.com`), but the `siteMonitor` status dot checks each service directly by IP, so a broken proxy does not hide which service is down. The container is stateless — rebuild with `terraform apply` + this playbook.

Tiles: Proxmox `pve`/`pve2`, portfolio, Cloudflare Tunnel, Grafana, the three k3s nodes, Immich, Nginx Proxy Manager and Pi-hole. Vaultwarden, Overleaf and the Obsidian DB are intentionally left out (not part of the thesis).

### 7. Deploy k3s workloads

Grafana and the portfolio are reachable from the LAN through NodePorts (`http://192.168.1.201:30300`, `:30080`); the router forwards none of them, Internet access still goes only through the Cloudflare Tunnel. Apply with (`helm` is installed on `k3s-master`):

```bash
helm upgrade --install kps prometheus-community/kube-prometheus-stack --version 90.0.0 \
  -n monitoring --create-namespace -f k8s/monitoring/prometheus-values.yml
kubectl apply -f k8s/manifests/
```

`cloudflared` reads the tunnel token from the `cloudflared-token` Secret, which is created by hand (`kubectl create secret generic cloudflared-token --from-literal=token=...`) and never stored in git.

## CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `terraform.yml` | PR / push on `terraform/**` | `fmt`, `init -backend=false`, `validate`, `test` |
| `ansible.yml` | PR / push on `ansible/**` | `ansible-lint`, `--syntax-check` (site, destroy, immich, homepage) |
| `tests.yml` | PR / push | static pytest suite |
| `manifests.yml` | PR / push on `k8s/**`, `immich/**` | `kubeconform` on manifests + rendered `kube-prometheus-stack`, unknown Helm values keys, `docker compose config` |
| `security.yml` | PR / push / weekly | `gitleaks` (full history), `trivy config` (HIGH/CRITICAL fail), `zizmor` workflow audit |

Actions are pinned to commit SHAs and downloaded tools to SHA256 checksums; every workflow runs with `contents: read`.
When upgrading `kube-prometheus-stack` in the cluster, bump `KPS_CHART_VERSION` in `manifests.yml`.

GitHub-hosted runners cannot reach `192.168.1.0/24`, so there is no remote `terraform apply` or `ansible-playbook` against the lab. Apply stays on a machine inside the LAN.

## Tests

Tests map to the thesis test methodology. Static tests run in CI; live tests need the LAN.

```bash
python -m venv .venv && .venv/bin/pip install -r tests/requirements.txt
cd tests
pytest                     # static only (CI)
pytest --live              # + read-only checks against the running lab
pytest --disruptive        # + reboots a worker / the Immich LXC, restarts services
./measure_rebuild.sh --yes # destroys + rebuilds k3s from code, times each phase
```

`terraform test` (in `terraform/environments/production`) plans against a mocked provider, so it needs no Proxmox.
Measurements are written to `tests/results/*.json` (gitignored).

| Claim | Test |
|-------|------|
| Environment reproducible from code | `terraform test`, `test_infrastructure_matches_terraform_code`, `test_hosts_converged_with_ansible`, `measure_rebuild.sh` |
| k3s separated from Immich | `test_k3s_cluster_and_immich_are_disjoint`, `test_k3s_not_scheduled_on_immich_host` |
| No open ports, access via tunnel / VPN | `test_no_k8s_service_exposed_outside_cluster`, `test_portfolio_served_through_cloudflare_tunnel`, `test_no_open_ports_on_public_ip`, `test_admin_ssh_over_tailscale` |
| Secrets outside git | `test_secret_files_never_committed`, `test_no_secret_literals_in_tracked_files`, `test_ansible_vault_files_are_encrypted` |
| Dashboard shows the thesis services | `test_homepage_shows_exactly_the_thesis_services`, `test_homepage_status_checks_bypass_the_reverse_proxy`, `test_homepage_dashboard_up`, `test_k3s_web_services_reachable_on_lan_nodeports` |
| Unprivileged LXC, pod resource limits | `test_immich_lxc_is_unprivileged`, `test_every_k3s_container_has_resource_limits`, `test_pods_stay_within_limits` |
| CPU / RAM usage, VM vs LXC overhead | `test_cluster_cpu_and_ram_have_headroom`, `test_lxc_shares_host_kernel_vm_has_its_own`, `test_vm_vs_lxc_baseline_overhead`, `test_lxc_restarts_faster_than_vm` |
| Node failure, updates, recovery time | `test_worker_node_failure_and_recovery`, `test_rolling_update_without_downtime`, `test_immich_stack_update` |

Optional env vars for live tests: `PORTFOLIO_URL`, `HOMELAB_PUBLIC_IP` (run from outside the LAN), `TAILSCALE_HOST`, `PROMETHEUS_URL`, `KUBECONFIG`, `HOMELAB_SSH_KEY`.

## Security notes

- `*.tfvars` and Terraform state are gitignored
- kubeconfig fetched by Ansible is written to `ansible/.kube/` (gitignored)
- Galaxy roles install under `ansible/roles/galaxy/` (gitignored) — use `requirements.yml`
- `.env` files and `ansible/credentials/` (generated Immich DB password) are gitignored
- join token is read from the live master during the playbook run — no manual Vault copy after recreate
- API tokens and private keys never belong in git
- k8s NodePorts (`30080`, `30300`) are LAN-only and explicitly allow-listed in `test_no_k8s_service_exposed_outside_cluster`; `test_no_open_ports_on_public_ip` checks them from outside
- Homepage has no API keys or widget secrets — status dots use plain HTTP checks
