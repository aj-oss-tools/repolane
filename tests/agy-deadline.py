#!/usr/bin/env python3
"""with-timeout.py <seconds> <cmd...>: run in its own process group, stdin closed; kill the whole group at the deadline, exit 124."""
import os, signal, subprocess, sys
limit = int(sys.argv[1])
p = subprocess.Popen(sys.argv[2:], stdin=subprocess.DEVNULL, start_new_session=True)
try:
    sys.exit(p.wait(timeout=limit))
except subprocess.TimeoutExpired:
    print(f"TIMEOUT after {limit}s: {' '.join(sys.argv[2:])}", file=sys.stderr)
    os.killpg(p.pid, signal.SIGTERM)
    try: p.wait(timeout=10)
    except subprocess.TimeoutExpired: os.killpg(p.pid, signal.SIGKILL)
    sys.exit(124)
