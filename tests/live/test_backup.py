"""Off-site backup of the Immich library (Backblaze B2, restic): freshness and a real restore."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from lab import IMMICH, ssh

pytestmark = pytest.mark.live

MAX_AGE = timedelta(hours=26)  # daily timer + randomized delay
DUMPS = "/mnt/photos/library/backups"


def latest_snapshot():
    out = ssh(IMMICH, "immich-backup snapshots --tag immich --latest 1 --json", timeout=120).stdout
    snaps = json.loads(out)
    assert snaps, "no restic snapshot in B2 yet: run `systemctl start immich-backup` on the Immich LXC"
    return snaps[-1]


def test_backup_timers_active():
    for unit in ("immich-backup.timer", "immich-backup-check.timer"):
        assert ssh(IMMICH, f"systemctl is-active {unit}").stdout.strip() == "active", unit


def test_last_backup_succeeded_and_is_recent():
    result = ssh(IMMICH, "systemctl show immich-backup.service -p Result --value").stdout.strip()
    assert result == "success", f"last run: {result}"
    taken = datetime.fromisoformat(latest_snapshot()["time"])
    assert datetime.now(timezone.utc) - taken < MAX_AGE, f"latest snapshot from {taken}"


def test_restore_db_dumps_from_b2(record):
    """Restore Immich's DB dumps from the latest snapshot and compare checksums with the originals."""
    snap = latest_snapshot()
    target = "/tmp/immich-restore-test"
    start = time.monotonic()
    ssh(IMMICH, f"rm -rf {target} && immich-backup restore {snap['short_id']} --target {target} --include {DUMPS}",
        timeout=1800)
    elapsed = time.monotonic() - start
    compare = (f"cd {target}{DUMPS} && sha256sum * | while read sum f; do "
               f"[ -f {DUMPS}/$f ] && echo \"$sum  {DUMPS}/$f\"; done | sha256sum -c --quiet && ls | wc -l")
    try:
        files = int(ssh(IMMICH, compare, timeout=300).stdout.strip())
        size = ssh(IMMICH, f"du -sb {target} | cut -f1").stdout.strip()
    finally:
        ssh(IMMICH, f"rm -rf {target}", check=False)
    assert files > 0, "restored snapshot contains no DB dump"
    record("immich_backup_restore", {"snapshot": snap["short_id"], "files": files,
                                     "bytes": int(size), "restore_s": round(elapsed, 1)})
