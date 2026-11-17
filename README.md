# Homelab Infrastructure

Infrastructure-as-code for a small Kubernetes cluster and a self-hosted photo library (Immich) on a two-node Proxmox cluster.

Terraform provisions Ubuntu VMs (k3s) on node `pve` and a Debian LXC (Immich) on node `pve2`. Ansible bootstraps [k3s](https://k3s.io/) and deploys [Immich](https://immich.app/) with Docker Compose. GitHub Actions validates Terraform and Ansible on every PR — apply stays local, because runners cannot reach the private LAN.

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
└──────────────┘     └────────────────┘     └────────────┬─────────────┘
                                                         │
                     ┌────────────────┐                  │
                     │    Ansible     │──────────────────┘
                     │ k3s + immich   │
                     └────────────────┘
```

| Host | Role | IP | Notes |
|------|------|----|--------|
| `k3s-master` | control plane | `192.168.1.201` | Ubuntu VM on `pve` |
| `k3s-worker-01` | agent | `192.168.1.202` | Ubuntu VM on `pve` |
| `k3s-worker-02` | agent | `192.168.1.203` | Ubuntu VM on `pve` |
| `immich` | photo library | `192.168.1.168` | Debian LXC + Docker on `pve2`; photos on a separate `local-lvm` volume → `/mnt/photos` |

k3s and Immich are separate: cluster workloads stay on k3s (`pve`); the photo library runs in its own LXC on a different node (`pve2`).

## Tech stack

- **Proxmox VE** — hypervisor
- **Terraform** + `bpg/proxmox` — VM + LXC lifecycle, static IPs
- **Ansible** — OS baseline, k3s, Docker, Compose deploy
- **k3s** — lightweight Kubernetes
- **Docker Compose** — Immich (server, machine learning, Valkey, Postgres)
- **GitHub Actions** — CI validation (no remote apply)

## Repository layout

```text
.
├── terraform/environments/production/   # k3s VMs + Immich LXC
├── ansible/
│   ├── requirements.yml                 # Galaxy roles (geerlingguy.docker)
│   ├── playbooks/
│   │   ├── site.yml                     # bootstrap k3s
│   │   ├── destroy-k3s.yml              # uninstall k3s
│   │   └── immich.yml                   # bootstrap Immich host
│   ├── inventory/
│   │   ├── production.ini
│   │   └── group_vars/                  # vars loaded with inventory
│   └── roles/
│       ├── common/                      # shared apt baseline
│       ├── k3s_common/                  # swap off, ip_forward, k3s script
│       ├── k3s_master/
│       ├── k3s_worker/
│       └── immich/                      # dirs + compose + .env + up
├── immich/
│   ├── docker-compose.yml               # official Immich stack
│   └── .env.example                     # template; real .env is rendered by Ansible
├── k8s/manifests/                       # portfolio + cloudflared
└── .github/workflows/                   # terraform + ansible CI
```

## Prerequisites

- Proxmox cluster with nodes `pve` and `pve2`
- Ubuntu cloud-init template (`VMID 9000`) on `pve` for k3s VMs
- The Debian LXC template for Immich is downloaded to `pve2` by Terraform
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

# Immich LXC (SSH key lands on root)
ssh -i ~/.ssh/proxmox_terraform root@192.168.1.168
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

## CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `terraform.yml` | PR / push on `terraform/**` | `fmt`, `init -backend=false`, `validate`, `test` |
| `ansible.yml` | PR / push on `ansible/**` | `ansible-lint`, `--syntax-check` |
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
