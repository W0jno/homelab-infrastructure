import subprocess
import time
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
RESULTS_DIR = Path(__file__).resolve().parent / "results"


def load_yaml_docs(path):
    with open(path) as f:
        return [d for d in yaml.safe_load_all(f) if d]


def run(cmd, cwd=REPO, check=True, timeout=600, env=None):
    return subprocess.run(cmd, cwd=cwd, check=check, timeout=timeout, capture_output=True, text=True, env=env)


def wait_until(predicate, timeout, interval=5):
    """Poll predicate until truthy; return elapsed seconds or raise on timeout."""
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return time.monotonic() - start
        time.sleep(interval)
    raise TimeoutError(f"condition not met within {timeout}s")
