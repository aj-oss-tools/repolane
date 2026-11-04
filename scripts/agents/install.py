#!/usr/bin/env python3
"""Writes a lane's agent files, for lib.sh. Not part of `lane agent`: a session can run that, and these change what it is
allowed to do. Every action starts with the Layout's fields (see lane_install in lib.sh).

  lane <layout…> <folder> <lane-id> <memory-dir>    a session folder of a lane; prints the paths to keep out of git
  rules <layout…> <lane-dir> <spec>                 the rules file at a lane's root
  folders <layout…>                                 what each session folder may reach
"""
import os
import sys

sys.dont_write_bytecode = True
sys.path[0] = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
import agents
from agents.base import Layout

N = len(Layout._fields)


def main(argv):
    cmd, layout, rest = argv[0] if argv else "", Layout(*argv[1:N + 1]) if len(argv) > N else None, argv[N + 1:]
    a = agents.get()
    if cmd == "lane" and layout and len(rest) == 3:
        for p in a.install_lane(layout, *rest): print(p)
    elif cmd == "rules" and layout and len(rest) == 2: a.install_lane_rules(layout, *rest)
    elif cmd == "folders" and layout and not rest: a.grant_lane_folders(layout)
    else:
        sys.stderr.write(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
