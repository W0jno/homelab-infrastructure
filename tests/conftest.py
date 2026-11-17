import json
import time

import pytest

from helpers import REPO, RESULTS_DIR, load_yaml_docs


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="run tests against the real homelab (LAN only)")
    parser.addoption("--disruptive", action="store_true", help="also run tests that reboot nodes / restart services")


def pytest_configure(config):
    config.addinivalue_line("markers", "live: needs access to the homelab LAN")
    config.addinivalue_line("markers", "disruptive: reboots nodes or restarts services")


def pytest_collection_modifyitems(config, items):
    live = config.getoption("--live") or config.getoption("--disruptive")
    disruptive = config.getoption("--disruptive")
    for item in items:
        if "live" in item.keywords and not live:
            item.add_marker(pytest.mark.skip(reason="needs --live"))
        if "disruptive" in item.keywords and not disruptive:
            item.add_marker(pytest.mark.skip(reason="needs --disruptive"))


@pytest.fixture(scope="session")
def k8s_docs():
    docs = []
    for path in sorted((REPO / "k8s" / "manifests").glob("*.yml")):
        docs += load_yaml_docs(path)
    return docs


@pytest.fixture(scope="session")
def compose():
    return load_yaml_docs(REPO / "immich" / "docker-compose.yml")[0]


@pytest.fixture(scope="session")
def record():
    """Store a measurement in tests/results/<name>.json for the thesis tables."""
    RESULTS_DIR.mkdir(exist_ok=True)

    def _record(name, data):
        data = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **data}
        (RESULTS_DIR / f"{name}.json").write_text(json.dumps(data, indent=2))
        print(f"\n[{name}] {json.dumps(data)}")

    return _record
