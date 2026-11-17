import json
import os
import socket
import subprocess
import time
from contextlib import contextmanager

import requests

from helpers import REPO, run

MASTER, WORKER_01, WORKER_02 = "192.168.1.201", "192.168.1.202", "192.168.1.203"
IMMICH = "192.168.1.168"
IMMICH_PORT = 2283
IMMICH_CONTAINERS = ["immich_server", "immich_machine_learning", "immich_redis", "immich_postgres"]
IMMICH_PING = f"http://{IMMICH}:{IMMICH_PORT}/api/server/ping"
NODES = {"k3s-master": MASTER, "k3s-worker-01": WORKER_01, "k3s-worker-02": WORKER_02}
SSH_KEY = os.path.expanduser(os.environ.get("HOMELAB_SSH_KEY", "~/.ssh/proxmox_terraform"))
KUBECONFIG = os.environ.get("KUBECONFIG", str(REPO / "ansible/.kube/config"))


def kubectl(*args, check=True):
    return run(["kubectl", "--kubeconfig", KUBECONFIG, *args], check=check, timeout=300)


def kubectl_json(*args):
    return json.loads(kubectl(*args, "-o", "json").stdout)


def ssh(host, command, user=None, check=True, timeout=60):
    user = user or ("root" if host == IMMICH else "ubuntu")
    return run(
        ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
         "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
         f"{user}@{host}", command],
        check=check, timeout=timeout,
    )


def port_open(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_ok(url, timeout=5):
    try:
        return requests.get(url, timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


def node_ready(name):
    res = kubectl("get", "node", name, "-o",
                  "jsonpath={.status.conditions[?(@.type=='Ready')].status}", check=False)
    return res.stdout.strip() == "True"


def deployments_available(namespace="default"):
    for d in kubectl_json("get", "deployments", "-n", namespace)["items"]:
        if d["status"].get("availableReplicas", 0) < d["spec"]["replicas"]:
            return False
    return True


@contextmanager
def port_forward(namespace, target, port):
    proc = subprocess.Popen(
        ["kubectl", "--kubeconfig", KUBECONFIG, "-n", namespace, "port-forward", target, f"{port}:{port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(30):
            if port_open("127.0.0.1", port, timeout=1):
                break
            time.sleep(0.5)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
