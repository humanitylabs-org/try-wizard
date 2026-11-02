#!/usr/bin/env python3
"""Serialize CI compilation/VM contracts with the host's existing heavy worker.

WIZARD_CI_WORKER_LOCK is configured on the runner, not in repository settings.
The child inherits the flock descriptor so cancellation cannot release the lock
while a surviving compiler or VM still holds it. No guest image is rebuilt here.
"""

import fcntl
import os
import subprocess
import sys
import time


def main():
    path = os.environ.get("WIZARD_CI_WORKER_LOCK")
    if not path or not os.path.isabs(path) or len(sys.argv) < 2:
        sys.exit("WIZARD_CI_WORKER_LOCK must be an absolute path; command required")
    timeout = float(os.environ.get("WIZARD_CI_LOCK_WAIT_SECONDS", "900"))
    if not 0 <= timeout <= 900:
        sys.exit("WIZARD_CI_LOCK_WAIT_SECONDS must be between 0 and 900")
    # Never truncate or unlink the shared worker lock (its inode is the lock).
    with open(path, "a+") as lock:
        deadline = time.monotonic() + timeout
        print("Waiting for shared heavy-worker lock", flush=True)
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    sys.exit("Timed out waiting for shared heavy-worker lock")
                time.sleep(min(1, max(0, deadline - time.monotonic())))
        print("Acquired shared heavy-worker lock", flush=True)
        return subprocess.call(sys.argv[1:], pass_fds=(lock.fileno(),))


if __name__ == "__main__":
    sys.exit(main())
