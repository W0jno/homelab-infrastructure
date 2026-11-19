"""Slide 10: security mechanisms, verified from the repository alone."""
import re
import subprocess

import pytest

from helpers import REPO, load_yaml_docs

SECRET_PATHS = re.compile(r"(\.tfvars(\.json)?$|\.tfstate(\..*)?$|(^|/)\.env$|(^|/)\.kube/)")
SECRET_CONTENT = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[\w.-]+@(pve|pam)![\w-]+=[0-9a-f-]{36}"),  # Proxmox API token
    re.compile(r"\bey[A-Za-z0-9_-]{100,}"),  # Cloudflare tunnel token (base64 JSON)
    re.compile(r"\bK10[0-9a-f]{40,}"),  # k3s node token
]


def tracked_files():
    out = subprocess.run(["git", "ls-files"], cwd=REPO, check=True, capture_output=True, text=True)
    return out.stdout.split()


def test_secret_files_never_committed():
    out = subprocess.run(
        ["git", "log", "--all", "--name-only", "--format="], cwd=REPO, check=True, capture_output=True, text=True
    )
    leaked = sorted({p for p in out.stdout.split() if SECRET_PATHS.search(p)})
    assert not leaked, f"secret-bearing files in git history: {leaked}"


@pytest.mark.parametrize("path", [".tfvars", ".tfstate", ".env", "ansible/.kube/config"])
def test_secret_files_are_gitignored(path):
    sample = {".tfvars": "terraform/environments/production/x.tfvars",
              ".tfstate": "terraform/environments/production/terraform.tfstate",
              ".env": "immich/.env"}.get(path, path)
    res = subprocess.run(["git", "check-ignore", "-q", "--no-index", sample], cwd=REPO, check=False)
    assert res.returncode == 0, f"{sample} is not gitignored"


def test_no_secret_literals_in_tracked_files():
    hits = []
    for rel in tracked_files():
        text = (REPO / rel).read_text(errors="ignore")
        hits += [f"{rel}: {p.pattern}" for p in SECRET_CONTENT if p.search(text)]
    assert not hits, hits


def test_ansible_vault_files_are_encrypted():
    vaults = [f for f in tracked_files() if f.endswith("vault.yml")]
    for rel in vaults:
        assert (REPO / rel).read_text().startswith("$ANSIBLE_VAULT;"), f"{rel} is plaintext"


def test_terraform_api_token_comes_from_variable():
    provider = (REPO / "terraform/environments/production/provider.tf").read_text()
    assert re.search(r"api_token\s*=\s*var\.proxmox_api_token", provider)


def test_cloudflared_token_comes_from_k8s_secret(k8s_docs):
    dep = next(d for d in k8s_docs if d["metadata"]["name"] == "cloudflared-deployment")
    env = {e["name"]: e for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert "secretKeyRef" in env["TUNNEL_TOKEN"]["valueFrom"]
    assert "value" not in env["TUNNEL_TOKEN"]


# LAN-only NodePorts linked from the Homepage dashboard; the router forwards none of them
# (checked from the Internet by tests/live/test_functional.py::SENSITIVE_PORTS).
LAN_NODEPORTS = {"portfolio-service": 30080}


def test_no_k8s_service_exposed_outside_cluster(k8s_docs):
    """Internet access goes only through the Cloudflare Tunnel: no LoadBalancer/hostPort,
    NodePort only for the explicitly listed LAN dashboard links."""
    for doc in k8s_docs:
        if doc["kind"] == "Service":
            name = doc["metadata"]["name"]
            svc_type = doc["spec"].get("type", "ClusterIP")
            if svc_type == "NodePort":
                assert [p.get("nodePort") for p in doc["spec"]["ports"]] == [LAN_NODEPORTS.get(name)], name
            else:
                assert svc_type == "ClusterIP", name
        if doc["kind"] == "Deployment":
            spec = doc["spec"]["template"]["spec"]
            assert not spec.get("hostNetwork"), doc["metadata"]["name"]
            for c in spec["containers"]:
                assert not any("hostPort" in p for p in c.get("ports", [])), c["name"]


def test_cloudflared_tunnel_is_highly_available(k8s_docs):
    dep = next(d for d in k8s_docs if d["metadata"]["name"] == "cloudflared-deployment")
    assert dep["spec"]["replicas"] >= 2
    assert dep["spec"]["template"]["spec"]["containers"][0]["livenessProbe"]["httpGet"]["path"] == "/ready"


def test_every_k3s_container_is_non_root_with_read_only_rootfs(k8s_docs):
    """Pods run as a non-root user, without privilege escalation, on a read-only root filesystem."""
    for doc in k8s_docs:
        if doc["kind"] != "Deployment":
            continue
        spec = doc["spec"]["template"]["spec"]
        assert spec.get("securityContext", {}).get("runAsNonRoot") is True, doc["metadata"]["name"]
        for c in spec["containers"]:
            sc = c.get("securityContext", {})
            assert sc.get("readOnlyRootFilesystem") is True, c["name"]
            assert sc.get("allowPrivilegeEscalation") is False, c["name"]
            assert sc.get("capabilities", {}).get("drop") == ["ALL"], c["name"]


def test_every_k3s_container_has_resource_limits(k8s_docs):
    missing = []
    for doc in k8s_docs:
        if doc["kind"] != "Deployment":
            continue
        for c in doc["spec"]["template"]["spec"]["containers"]:
            limits = c.get("resources", {}).get("limits", {})
            if not {"cpu", "memory"} <= limits.keys():
                missing.append(f'{doc["metadata"]["name"]}/{c["name"]}')
    assert not missing, f"containers without cpu+memory limits: {missing}"


def test_monitoring_stack_has_resource_limits():
    values = load_yaml_docs(REPO / "k8s/monitoring/prometheus-values.yml")[0]
    limits = values["prometheus"]["prometheusSpec"]["resources"]["limits"]
    assert {"cpu", "memory"} <= limits.keys()


def test_immich_lxc_is_unprivileged():
    immich_tf = (REPO / "terraform/environments/production/immich.tf").read_text()
    assert re.search(r"unprivileged\s*=\s*true", immich_tf)


def test_immich_db_password_not_in_git():
    defaults = (REPO / "ansible/roles/immich/defaults/main.yml").read_text()
    assert "ansible.builtin.password" in defaults
    res = subprocess.run(["git", "check-ignore", "-q", "--no-index", "ansible/credentials/immich_db_password"],
                         cwd=REPO, check=False)
    assert res.returncode == 0, "ansible/credentials/ is not gitignored"


def test_immich_containers_do_not_run_privileged(compose):
    for name, svc in compose["services"].items():
        assert not svc.get("privileged"), name
        assert svc.get("network_mode") != "host", name


def test_traefik_is_disabled():
    """No Ingress uses Traefik; k3s must not deploy it (it would open 80/443 on every node)."""
    defaults = load_yaml_docs(REPO / "ansible/roles/k3s_master/defaults/main.yml")[0]
    assert "traefik" in defaults["k3s_master_disable_components"]
    config = (REPO / "ansible/roles/k3s_master/templates/config.yaml.j2").read_text()
    assert "k3s_master_disable_components" in config
