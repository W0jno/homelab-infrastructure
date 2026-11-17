"""Slide 11, functional tests: deploy from code, service availability, tunnel and VPN access."""
import os
import re

import pytest
import requests

from helpers import REPO, run
from lab import IMMICH, IMMICH_CONTAINERS, IMMICH_PING, IMMICH_PORT, NODES, deployments_available, kubectl_json, port_open, ssh

pytestmark = pytest.mark.live

# Ports that must NOT be reachable from the Internet (SSH, k8s API, Proxmox UI, Immich).
SENSITIVE_PORTS = [22, 80, 443, 2000, 3000, 6443, 8006, IMMICH_PORT]


def test_all_k3s_nodes_ready():
    nodes = {n["metadata"]["name"]: n for n in kubectl_json("get", "nodes")["items"]}
    assert set(nodes) == set(NODES)
    for name, node in nodes.items():
        ready = next(c for c in node["status"]["conditions"] if c["type"] == "Ready")
        assert ready["status"] == "True", name
        ip = next(a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP")
        assert ip == NODES[name]


def test_control_plane_and_agents_roles():
    nodes = kubectl_json("get", "nodes")["items"]
    masters = [n["metadata"]["name"] for n in nodes
               if "node-role.kubernetes.io/control-plane" in n["metadata"]["labels"]]
    assert masters == ["k3s-master"]


def test_workloads_available():
    assert deployments_available("default")


def test_cloudflared_pods_spread_across_nodes():
    pods = kubectl_json("get", "pods", "-l", "pod=cloudflared")["items"]
    running = [p for p in pods if p["status"]["phase"] == "Running"]
    assert len(running) >= 2
    assert len({p["spec"]["nodeName"] for p in running}) >= 2, "both tunnel replicas on one node"


def test_monitoring_pods_running():
    pods = kubectl_json("get", "pods", "-A")["items"]
    names = [p["metadata"]["name"] for p in pods if p["status"]["phase"] == "Running"]
    assert any(n.startswith("prometheus-") for n in names)
    assert any("grafana" in n for n in names)


def test_k3s_not_scheduled_on_immich_host():
    """Conclusion 02: the Immich LXC is not a cluster member."""
    ips = [a["address"] for n in kubectl_json("get", "nodes")["items"] for a in n["status"]["addresses"]]
    assert IMMICH not in ips


def test_immich_health():
    r = requests.get(IMMICH_PING, timeout=10)
    assert r.status_code == 200 and r.json() == {"res": "pong"}


def test_immich_containers_running():
    out = ssh(IMMICH, "docker ps --format '{{.Names}} {{.State}}'").stdout.split("\n")
    states = dict(line.split() for line in out if line)
    for container in IMMICH_CONTAINERS:
        assert states.get(container) == "running", container


def test_portfolio_served_through_cloudflare_tunnel(env):
    r = requests.get(env("PORTFOLIO_URL"), timeout=15)
    assert r.status_code == 200
    assert r.headers.get("server", "").lower() == "cloudflare"
    assert "cf-ray" in r.headers


def test_no_open_ports_on_public_ip(env):
    """Conclusion 03. Run from OUTSIDE the LAN (e.g. phone hotspot), hairpin NAT skews results."""
    public_ip = env("HOMELAB_PUBLIC_IP")
    opened = [p for p in SENSITIVE_PORTS if port_open(public_ip, p)]
    assert not opened, f"ports reachable from the Internet: {opened}"


def test_admin_ssh_over_tailscale(env):
    assert port_open(env("TAILSCALE_HOST"), 22), "SSH not reachable over Tailscale"


def test_infrastructure_matches_terraform_code():
    """Reproducibility: real Proxmox state equals the code (no drift)."""
    tf_dir = REPO / "terraform/environments/production"
    if not (tf_dir / "production.auto.tfvars").exists():
        pytest.skip("production.auto.tfvars missing")
    res = run(["terraform", "plan", "-detailed-exitcode", "-input=false", "-lock=false", "-no-color"],
              cwd=tf_dir, check=False)
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-2000:]


def changed_tasks(output):
    """Pairs of (task, host) reported as changed by the default ansible callback."""
    task, changed = None, []
    for line in output.splitlines():
        if m := re.match(r"TASK \[(?:[\w.]+ : )?(.+?)\]", line):
            task = m.group(1)
        elif m := re.match(r"changed: \[([^\]]+)\]", line):
            changed.append((task, m.group(1)))
    return changed


@pytest.mark.parametrize("playbook", ["site.yml", "immich.yml"])
def test_hosts_converged_with_ansible(playbook):
    """Idempotency: a --check run against the live hosts reports nothing to change."""
    res = run(["ansible-playbook", f"playbooks/{playbook}", "--check"], cwd=REPO / "ansible", check=False,
              timeout=1200, env={**os.environ, "ANSIBLE_DISPLAY_OK_HOSTS": "false",
                                 "ANSIBLE_DISPLAY_SKIPPED_HOSTS": "false", "ANSIBLE_NOCOLOR": "1"})
    assert "No module named 'ansible_collections.ansible.posix'" not in res.stderr, \
        "ansible.posix collection missing: ansible-galaxy collection install ansible.posix -p ansible/collections"
    assert res.returncode == 0, res.stdout[-3000:] + res.stderr[-2000:]
    drift = [f"{host}: {task}" for task, host in changed_tasks(res.stdout)
             if task != "Update cache"]  # apt cache age is not drift
    assert not drift, drift
