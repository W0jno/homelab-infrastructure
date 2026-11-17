"""Slides 5-9: architecture, separation of k3s and the Immich LXC, monitoring config."""
import configparser
import re

from helpers import REPO, load_yaml_docs

EXPECTED_HOSTS = {
    "k3s_master": ["192.168.1.201"],
    "k3s_worker": ["192.168.1.202", "192.168.1.203"],
    "immich": ["192.168.1.168"],
}


def inventory():
    cp = configparser.ConfigParser(allow_no_value=True, delimiters=(" ",))
    cp.optionxform = str
    cp.read(REPO / "ansible/inventory/production.ini")
    return {s: list(cp[s].keys()) for s in cp.sections()}


def test_inventory_matches_architecture():
    inv = inventory()
    for group, hosts in EXPECTED_HOSTS.items():
        assert inv[group] == hosts, group
    assert set(inv["k3s_cluster:children"]) == {"k3s_master", "k3s_worker"}


def test_k3s_cluster_and_immich_are_disjoint():
    """Conclusion 02: the k3s cluster is separated from the Immich host."""
    inv = inventory()
    cluster = set(inv["k3s_master"]) | set(inv["k3s_worker"])
    assert cluster.isdisjoint(inv["immich"])


def plays(name):
    return load_yaml_docs(REPO / "ansible/playbooks" / name)[0]


def test_site_playbook_targets_only_k3s():
    assert {p["hosts"] for p in plays("site.yml")} <= {"k3s_cluster", "k3s_master", "k3s_worker"}


def test_immich_playbook_targets_only_immich_and_uses_docker():
    immich_plays = plays("immich.yml")
    assert {p["hosts"] for p in immich_plays} == {"immich"}
    roles = [r if isinstance(r, str) else r["role"] for r in immich_plays[0]["roles"]]
    assert "geerlingguy.docker" in roles and "immich" in roles


def test_workers_join_master_from_inventory():
    """Join token and URL come from the live master, so a rebuild needs no manual copy."""
    worker_vars = load_yaml_docs(REPO / "ansible/inventory/group_vars/k3s_worker/vars.yml")[0]
    assert "groups['k3s_master'][0]" in worker_vars["k3s_url"]
    worker_tasks = (REPO / "ansible/roles/k3s_worker/tasks/main.yml").read_text()
    assert "hostvars[groups['k3s_master'][0]]['k3s_master_node_token']" in worker_tasks


def test_k3s_version_is_pinned():
    all_vars = load_yaml_docs(REPO / "ansible/inventory/group_vars/all.yml")[0]
    assert re.fullmatch(r"v\d+\.\d+\.\d+\+k3s\d+", all_vars["k3s_version"])


def test_immich_stack_has_expected_services(compose):
    assert {"immich-server", "immich-machine-learning", "redis", "database"} <= compose["services"].keys()
    for name, svc in compose["services"].items():
        assert svc.get("restart") in {"unless-stopped", "always"}, name


def test_immich_data_comes_from_env_locations(compose):
    """Library and DB paths are set in .env (rendered by Ansible), not hard-coded in compose."""
    hosts = {vol.split(":")[0] for svc in compose["services"].values() for vol in svc.get("volumes", [])}
    assert {"${UPLOAD_LOCATION}", "${DB_DATA_LOCATION}"} <= hosts
    defaults = load_yaml_docs(REPO / "ansible/roles/immich/defaults/main.yml")[0]
    assert defaults["immich_upload_location"].startswith("/mnt/photos/")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", defaults["immich_version"])


def test_prometheus_retention_is_7_days():
    values = load_yaml_docs(REPO / "k8s/monitoring/prometheus-values.yml")[0]
    assert values["prometheus"]["prometheusSpec"]["retention"] == "7d"


def test_grafana_dashboard_shows_cpu_and_ram():
    dashboard = (REPO / "k8s/monitoring/dashboards/homelab-overview.json").read_text()
    assert "node_cpu_seconds_total" in dashboard
    assert "node_memory_MemAvailable_bytes" in dashboard


def test_ansible_reads_group_vars_only_from_inventory():
    """Ansible ignores group_vars that are next to neither the inventory nor the playbooks."""
    assert not (REPO / "ansible/group_vars").exists()
    assert not (REPO / "ansible/playbooks/group_vars").exists()
