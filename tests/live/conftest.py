import os

import pytest
import requests

from lab import kubectl_json, port_forward


@pytest.fixture(scope="session")
def prometheus():
    """Prometheus base URL: PROMETHEUS_URL, or a port-forward to the operator's service."""
    if url := os.environ.get("PROMETHEUS_URL"):
        yield url
        return
    svcs = kubectl_json("get", "svc", "-A", "--field-selector", "metadata.name=prometheus-operated")["items"]
    if not svcs:
        pytest.fail("prometheus-operated service not found; set PROMETHEUS_URL")
    with port_forward(svcs[0]["metadata"]["namespace"], "svc/prometheus-operated", 9090) as url:
        yield url


@pytest.fixture(scope="session")
def promql(prometheus):
    def query(expr):
        r = requests.get(f"{prometheus}/api/v1/query", params={"query": expr}, timeout=10)
        r.raise_for_status()
        return r.json()["data"]["result"]
    return query


@pytest.fixture
def env():
    def get(name):
        value = os.environ.get(name)
        if not value:
            pytest.skip(f"set {name} to run this test")
        return value
    return get
