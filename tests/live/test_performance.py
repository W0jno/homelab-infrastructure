"""Slide 11, performance tests: CPU/RAM usage, VM vs LXC overhead, monitoring."""
import re

import pytest
import requests

from lab import IMMICH, NODES, WORKER_01, ssh

pytestmark = pytest.mark.live

MAX_USAGE_PERCENT = 90


def by_node(result):
    return {r["metric"].get("nodename", r["metric"].get("instance")): float(r["value"][1]) for r in result}


def test_node_exporter_scrapes_every_node(promql):
    up = promql('up{job="node-exporter"} == 1')
    assert len(up) == len(NODES)


def duration_seconds(value):
    """Prometheus duration ("1w", "7d", "1d12h") in seconds."""
    units = {"y": 31536000, "w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}
    return sum(int(n) * units[u] for n, u in re.findall(r"(\d+)([ywdhms])", value))


def test_prometheus_retention_is_7_days(prometheus):
    flags = requests.get(f"{prometheus}/api/v1/status/flags", timeout=10).json()["data"]
    # Prometheus normalises 7d to 1w in its flags.
    assert duration_seconds(flags["storage.tsdb.retention.time"]) == 7 * 86400


def test_cluster_cpu_and_ram_have_headroom(promql, record):
    cpu = by_node(promql(
        '100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{mode="idle"}[5m])))'
        ' * on(instance) group_left(nodename) node_uname_info'))
    ram = by_node(promql(
        '100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)'
        ' * on(instance) group_left(nodename) node_uname_info'))
    record("cluster_usage", {"cpu_percent": cpu, "ram_percent": ram})
    assert set(cpu) == set(NODES) and set(ram) == set(NODES)
    for node in NODES:
        assert cpu[node] < MAX_USAGE_PERCENT, f"{node} CPU {cpu[node]:.1f}%"
        assert ram[node] < MAX_USAGE_PERCENT, f"{node} RAM {ram[node]:.1f}%"


def test_pods_stay_within_limits(promql, record):
    usage = promql('sum by (pod) (container_memory_working_set_bytes{namespace="default", container!=""})')
    limits = promql('sum by (pod) (kube_pod_container_resource_limits{namespace="default", resource="memory"})')
    limit_by_pod = {r["metric"]["pod"]: float(r["value"][1]) for r in limits}
    ratios = {r["metric"]["pod"]: float(r["value"][1]) / limit_by_pod[r["metric"]["pod"]]
              for r in usage if r["metric"]["pod"] in limit_by_pod}
    record("pod_memory_vs_limit", ratios)
    assert all(ratio < 1 for ratio in ratios.values()), ratios


def mem_used_mib(host):
    meminfo = dict(re.findall(r"(\w+):\s+(\d+)", ssh(host, "cat /proc/meminfo").stdout))
    return (int(meminfo["MemTotal"]) - int(meminfo["MemAvailable"])) // 1024


def test_lxc_shares_host_kernel_vm_has_its_own():
    """Slide 4: containers share the host kernel, VMs boot their own."""
    lxc_kernel = ssh(IMMICH, "uname -r").stdout.strip()
    vm_kernel = ssh(WORKER_01, "uname -r").stdout.strip()
    assert lxc_kernel.endswith("-pve"), f"LXC kernel {lxc_kernel} is not the Proxmox host kernel"
    assert not vm_kernel.endswith("-pve"), f"VM kernel {vm_kernel} looks like the host kernel"


def test_vm_vs_lxc_baseline_overhead(record):
    """Memory and process count of the OS itself, excluding the workloads (k3s / Docker)."""
    vm_os_procs = int(ssh(WORKER_01, "ps -e --no-headers | grep -cvE 'k3s|containerd|pause'").stdout)
    lxc_os_procs = int(ssh(IMMICH, "ps -e --no-headers | grep -cvE 'docker|containerd'").stdout)
    vm_kernel_mib = int(ssh(WORKER_01, "awk '/^(Slab|KernelStack|PageTables):/ {s+=$2} END {print int(s/1024)}' "
                                       "/proc/meminfo").stdout)
    data = {
        "vm": {"host": WORKER_01, "mem_used_mib": mem_used_mib(WORKER_01), "kernel_mem_mib": vm_kernel_mib,
               "os_processes": vm_os_procs},
        "lxc": {"host": IMMICH, "mem_used_mib": mem_used_mib(IMMICH), "kernel_mem_mib": "shared with host",
                "os_processes": lxc_os_procs},
    }
    record("vm_vs_lxc_overhead", data)
    assert lxc_os_procs < vm_os_procs, "LXC should run fewer OS processes than a full VM"
