#!/usr/bin/env python3
"""Point Claude Code at the status line, without disturbing anything else in the file."""
import json, os, sys

path = sys.argv[1]
# the command to run: scripts/init passes it (an absolute one when the product lives outside the workspace)
command = sys.argv[2] if len(sys.argv) > 2 else '"$CLAUDE_PROJECT_DIR"/scripts/statusline.sh'
os.makedirs(os.path.dirname(path), exist_ok=True)
data = {}
if os.path.exists(path):
    try:
        data = json.load(open(path))
    except ValueError:
        sys.exit("settings.json is not valid JSON; leaving it alone")
if "statusLine" in data:
    sys.exit(0)
data["statusLine"] = {
    "type": "command",
    "command": command,
}
json.dump(data, open(path, "w"), indent=2)
print("statusLine added")
