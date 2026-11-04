#!/usr/bin/env python3
"""lane agent <action>: what bash needs from the adapter. Read-only: it answers questions and writes nothing, because a
session can run it. (Writing a lane's agent files is scripts/agents/install.py, which only lib.sh calls.)

  name                                 the agent
  has <capability>                     exit 0 when it can (see Capability in base.py), 1 when not
  capabilities                         everything it can, one per line
  rules-file                           the file it loads its instructions from
  session-dir <folder>                 where sessions started in that folder keep their transcripts
  session-count <folder>               how many there are
  sessions <n> <repo> [<folder>...]    the newest n past conversations of those folders
  session-owner <session-id> <repos>   which mirror under <repos> a conversation is filed under ("" when none)
  session-start-input                  hook JSON on stdin -> source, session id and cwd on one line
"""
import datetime
import os
import sys

sys.dont_write_bytecode = True
sys.path[0] = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
import agents
from agents.base import Capability


def main(argv):
    a = agents.get()
    cmd = argv[0] if argv else ""
    if cmd == "name" and len(argv) == 1: print(a.name)
    elif cmd == "has" and len(argv) == 2: return 0 if argv[1] in {c.value for c in a.capabilities} else 1
    elif cmd == "capabilities" and len(argv) == 1:
        for v in sorted(c.value for c in a.capabilities): print(v)
    elif cmd == "rules-file" and len(argv) == 1: print(a.rules_file)
    elif cmd == "session-dir" and len(argv) == 2: print(a.session_dir(argv[1]))
    elif cmd == "session-count" and len(argv) == 2: print(a.session_count(argv[1]))
    elif cmd == "session-owner" and len(argv) == 3: print(a.session_owner(argv[1], argv[2]))
    elif cmd == "session-start-input" and len(argv) == 1: print(*a.session_start_input(sys.stdin.read()))
    elif cmd == "sessions" and len(argv) >= 3:
        n, repo = int(argv[1]), argv[2]
        rows = a.sessions(argv[3:])
        print(f"Resumable conversations for {repo} ({a.resume_hint}):")
        for s in rows[:n]:
            print(f"  {datetime.datetime.fromtimestamp(s.last):%Y-%m-%d %H:%M}  {s.id}  {s.turns:>3} turns  {s.first}")
        if not rows: print("  none")
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
