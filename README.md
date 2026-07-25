# Homelab Kubernetes Platform

Infrastructure-as-code for a small Kubernetes cluster on Proxmox.

Terraform provisions Ubuntu VMs from a cloud-init template. Ansible hardens the OS and bootstraps [k3s](https://k3s.io/) (1 server + 2 agents). GitHub Actions validates Terraform and Ansible on every PR — apply stays local, because runners cannot reach the private LAN.

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
│  Terraform   │────▶│    Proxmox     │────▶│  k3s-master  .201        │
│  bpg/proxmox │     │  template 9000 │     │  k3s-worker  .202 / .203 │
└──────────────┘     └────────────────┘     └────────────┬─────────────┘
                                                         │
                     ┌────────────────┐                  │
                     │    Ansible     │──────────────────┘
                     │ common + k3s   │
                     └────────────────┘
```

| Node | Role | IP | Specs (default) |
|------|------|----|-----------------|
| `k3s-master` | control plane | `192.168.1.201` | 2 vCPU / 4 GB |
| `k3s-worker-01` | agent | `192.168.1.202` | 1 vCPU / 2 GB |
| `k3s-worker-02` | agent | `192.168.1.203` | 1 vCPU / 2 GB |

## Tech stack

- **Proxmox VE** — hypervisor
- **Terraform** + `bpg/proxmox` — VM lifecycle, Cloud-Init, static IPs
- **Ansible** — OS baseline, k3s install, automated kubeconfig export
- **k3s** — lightweight Kubernetes
- **GitHub Actions** — CI validation (no remote apply)

## Repository layout

```text
.
├── terraform/environments/production/   # Proxmox VMs
├── ansible/
│   ├── playbooks/
│   │   ├── site.yml                     # bootstrap cluster
│   │   └── destroy-k3s.yml              # uninstall k3s
│   ├── inventory/
│   │   ├── production.ini
│   │   └── group_vars/                  # vars loaded with inventory
│   └── roles/
│       ├── common/
│       ├── k3s_master/
│       └── k3s_worker/
├── k8s/manifests/                       # sample workloads
└── .github/workflows/                   # terraform + ansible CI
```

## Prerequisites

- Proxmox node with Ubuntu cloud-init template (`VMID 9000`)
- Terraform >= 1.10
- Ansible + `ansible.posix` collection
- SSH key pair used by Cloud-Init
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
```

### 2. Provision VMs

```bash
cd terraform/environments/production
terraform init
terraform apply
terraform output
```

Wait until SSH is up on all three nodes:

```bash
ssh -i ~/.ssh/proxmox_terraform ubuntu@192.168.1.201
```

### 3. Bootstrap k3s

```bash
cd ../../../ansible
ansible k3s_cluster -m ping
ansible-playbook playbooks/site.yml
```

Ansible will:
1. harden all nodes (`common`)
2. install k3s server on master
3. read the join token from master and join workers automatically
4. write a ready-to-use kubeconfig to `ansible/.kube/config` (API address rewritten from `127.0.0.1` to the master IP)

### 4. Verify cluster

```bash
export KUBECONFIG=$PWD/.kube/config
kubectl get nodes -o wide
```

Expected: three nodes in `Ready` state.

## CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `terraform.yml` | PR / push on `terraform/**` | `fmt`, `init -backend=false`, `validate` |
| `ansible.yml` | PR / push on `ansible/**` | `ansible-lint`, `--syntax-check` |

GitHub-hosted runners cannot reach `192.168.1.0/24`, so there is no remote `terraform apply` or `ansible-playbook` against the lab. Apply stays on a machine inside the LAN.

## Security notes

- `*.tfvars` and Terraform state are gitignored
- kubeconfig fetched by Ansible is written to `ansible/.kube/` (gitignored)
- join token is read from the live master during the playbook run — no manual Vault copy after recreate
- API tokens and private keys never belong in git
