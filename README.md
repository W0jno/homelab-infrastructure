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
- **Ansible** — OS baseline, k3s install, Vault for join token
- **k3s** — lightweight Kubernetes
- **GitHub Actions** — CI validation (no remote apply)

## Repository layout

```text
.
├── terraform/environments/production/   # Proxmox VMs
├── ansible/
│   ├── site.yml                         # entry playbook
│   ├── inventory/production.ini
│   ├── group_vars/                      # shared + vaulted secrets
│   └── roles/
│       ├── common/                      # packages, swap, sysctl
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
proxmox_endpoint  = "https://192.168.1.122:8006/"
proxmox_api_token = "terraform@pve!token=..."
ssh_ubuntu_key    = "ssh-ed25519 AAAA... terraform-proxmox"

k3s_nodes = {
  # vm_id, name, ip, gateway, netmask, dns, memory, cores
}
```

Store the k3s node join token in Ansible Vault:

```bash
cd ansible
ansible-vault edit group_vars/k3s_worker/vault.yml
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
ansible k3s_cluster -m ping --ask-vault-pass
ansible-playbook site.yml --ask-vault-pass
```

After a fresh master recreate, refresh the token from the server before joining workers:

```bash
ssh -i ~/.ssh/proxmox_terraform ubuntu@192.168.1.201 \
  "sudo cat /var/lib/rancher/k3s/server/node-token"
```

### 4. Verify cluster

```bash
ssh -i ~/.ssh/proxmox_terraform ubuntu@192.168.1.201 \
  "sudo k3s kubectl get nodes -o wide"
```

Expected: three nodes in `Ready` state.

Optional — use kubectl from your laptop:

```bash
scp -i ~/.ssh/proxmox_terraform \
  ubuntu@192.168.1.201:/etc/rancher/k3s/k3s.yaml ~/.kube/config-homelab
# replace 127.0.0.1 with 192.168.1.201, then:
export KUBECONFIG=~/.kube/config-homelab
kubectl get nodes -o wide
```

## CI

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `terraform.yml` | PR / push on `terraform/**` | `fmt`, `init -backend=false`, `validate` |
| `ansible.yml` | PR / push on `ansible/**` | `ansible-lint`, `--syntax-check` |

GitHub-hosted runners cannot reach `192.168.1.0/24`, so there is no remote `terraform apply` or `ansible-playbook` against the lab. Apply stays on a machine inside the LAN.

## Security notes

- `*.tfvars` and Terraform state are gitignored
- k3s join token lives in Ansible Vault, not plaintext YAML
- API tokens and private keys never belong in git
- Recreating the master rotates the cluster CA — update Vault before re-joining workers

## Roadmap

- [ ] Sample app with Service + Ingress
- [ ] GitOps (Argo CD)
- [ ] Monitoring (kube-prometheus-stack)
- [ ] Self-hosted runner for real apply from CI

## License

Private homelab project.
