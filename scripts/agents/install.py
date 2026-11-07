#!/usr/bin/env python3
"""Writes a lane's agent files, for lib.sh. Not part of `lane agent`: a session can run that, and these change what it is
allowed to do. Every action starts with the Layout's fields (see lane_install in lib.sh).

  lane <layout…> <folder> <lane-id> <memory-dir>    a session folder of a lane; prints the paths to keep out of git
  rules <layout…> <lane-dir> <spec>                 the rules file at a lane's root
  folders <layout…>                                 what each session folder may reach
  check-repo <layout…> <mirror> <ref>               refuse a ref the agent's files cannot be installed over
  record-session <layout…> <agent> <lane>           hook body on stdin: note which lane a new conversation is in
Claude Code's files are always written; an agent the workspace opts in to gets its own as well.
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path[0] = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
import agents
from agents.base import AgentRefusal, Layout

N = len(Layout._fields)


def main(argv):
    cmd, layout, rest = argv[0] if argv else "", Layout(*argv[1:N + 1]) if len(argv) > N else None, argv[N + 1:]
    if not layout:
        sys.stderr.write(__doc__)
        return 2
    if cmd == "record-session" and len(rest) == 2:
        a = agents.get(rest[0])
        a.record_session(a.parse_event(sys.stdin.read(), "session-start"), rest[1], layout.cache)
        return 0
    extra = agents.configured(f"{layout.ad}/.repolane/config.yml") if layout.mode == "workspace" else ""
    every = [agents.get()] + ([agents.get(extra)] if extra and extra != agents.DEFAULT else [])
    try:
        for a in every:
            if cmd == "lane" and len(rest) == 3:
                for p in a.install_lane(layout, *rest): print(p)
            elif cmd == "rules" and len(rest) == 2: a.install_lane_rules(layout, *rest)
            elif cmd == "folders" and not rest: a.grant_lane_folders(layout)
            elif cmd == "check-repo" and len(rest) == 2:
                why = a.check_repo(*rest)
                if why: raise AgentRefusal(why)
            else:
                sys.stderr.write(__doc__)
                return 2
    except AgentRefusal as e:
        sys.stderr.write(f"error: {e}\n")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
