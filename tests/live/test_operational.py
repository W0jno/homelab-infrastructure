"""Slide 11, operational tests: node failure, service updates, recovery time.

Every test here reboots or restarts something. Run with --disruptive, ideally in a maintenance window.
"""
import os
import threading
import time

import pytest

from helpers import wait_until
from lab import (IMMICH, IMMICH_PING, WORKER_02, deployments_available, http_ok, kubectl,
                 node_ready, port_open, ssh)

pytestmark = [pytest.mark.live, pytest.mark.disruptive]

RECOVERY_TIMEOUT = 600
restart_seconds = {}


class Prober(threading.Thread):
    """Polls a URL once per second and counts failures while a test disrupts the lab."""

    def __init__(self, url):
        super().__init__(daemon=True)
        self.url, self.ok, self.failed = url, 0, 0
        self._done = threading.Event()

    def run(self):
        while not self._done.is_set():
            if self.url and http_ok(self.url):
                self.ok += 1
            elif self.url:
                self.failed += 1
            time.sleep(1)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self._done.set()
        self.join()

    @property
    def availability(self):
        total = self.ok + self.failed
        return None if total == 0 else round(100 * self.ok / total, 2)


def reboot(host):
    ssh(host, "sudo systemctl reboot" if host != IMMICH else "systemctl reboot", check=False, timeout=15)
    wait_until(lambda: not port_open(host, 22, timeout=1), timeout=120, interval=1)


def test_worker_node_failure_and_recovery(record):
    """A worker goes down: the cluster notices, keeps serving, and heals by itself."""
    url = os.environ.get("PORTFOLIO_URL")
    with Prober(url) as probe:
        start = time.monotonic()
        reboot(WORKER_02)
        ssh_back = wait_until(lambda: port_open(WORKER_02, 22, timeout=1), RECOVERY_TIMEOUT, interval=1)
        ready = wait_until(lambda: node_ready("k3s-worker-02"), RECOVERY_TIMEOUT, interval=2)
        healed = wait_until(deployments_available, RECOVERY_TIMEOUT, interval=2)
        total = time.monotonic() - start
    restart_seconds["vm"] = ssh_back
    record("worker_failure", {
        "node": "k3s-worker-02", "ssh_back_s": round(ssh_back, 1), "node_ready_s": round(ready, 1),
        "workloads_available_s": round(healed, 1), "total_recovery_s": round(total, 1),
        "portfolio_availability_percent": probe.availability,
    })
    assert total < RECOVERY_TIMEOUT
    if probe.availability is not None:
        # The tunnel runs 2 replicas; losing one worker must not take the site down for long.
        assert probe.availability >= 90


def test_immich_lxc_restart(record):
    start = time.monotonic()
    reboot(IMMICH)
    ssh_back = wait_until(lambda: port_open(IMMICH, 22, timeout=1), RECOVERY_TIMEOUT, interval=1)
    immich = wait_until(lambda: http_ok(IMMICH_PING), RECOVERY_TIMEOUT, interval=1)
    restart_seconds["lxc"] = ssh_back
    record("immich_restart", {"ssh_back_s": round(ssh_back, 1),
                              "immich_healthy_s": round(time.monotonic() - start, 1),
                              "immich_after_ssh_s": round(immich, 1)})


def test_lxc_restarts_faster_than_vm():
    """Slide 4: containers start faster than virtual machines."""
    if {"vm", "lxc"} - restart_seconds.keys():
        pytest.skip("needs both restart measurements from this run")
    assert restart_seconds["lxc"] < restart_seconds["vm"], restart_seconds


@pytest.mark.parametrize("deployment", ["portfolio-deployment", "cloudflared-deployment"])
def test_rolling_update_without_downtime(deployment, record):
    url = os.environ.get("PORTFOLIO_URL")
    with Prober(url) as probe:
        start = time.monotonic()
        kubectl("rollout", "restart", f"deployment/{deployment}")
        kubectl("rollout", "status", f"deployment/{deployment}", "--timeout=300s")
        elapsed = time.monotonic() - start
    record(f"rollout_{deployment}", {"rollout_s": round(elapsed, 1),
                                     "availability_percent": probe.availability})
    if probe.availability is not None:
        assert probe.failed == 0, f"{probe.failed} failed requests during rollout"


def test_immich_stack_update(record):
    """Pull new images and recreate containers, then wait until Immich answers again."""
    start = time.monotonic()
    ssh(IMMICH, "cd /opt/immich && docker compose pull -q && docker compose up -d", timeout=1800)
    wait_until(lambda: http_ok(IMMICH_PING), RECOVERY_TIMEOUT, interval=2)
    record("immich_update", {"update_s": round(time.monotonic() - start, 1)})

