#!/usr/bin/env bash
# Claude Code status line (design A): line 1 = where you are, line 2 = only repos that need attention.
# PRODUCT (this script's own files) and AD (the workspace it reports on): one folder in a clone, see scripts/lib.sh
PRODUCT="${LANE_PRODUCT:-$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "${BASH_SOURCE[0]}")")/.." && pwd)}"
AD="${LANE_WORKSPACE:-$PRODUCT}"
input=$(cat)
source "$PRODUCT/scripts/gitstate.sh" 2>/dev/null || { lane_unpushed(){ echo "?"; }; lane_dirty_count(){ git -C "$1" status --porcelain 2>/dev/null | wc -l | tr -d " "; }; }
read -r cwd model ctx <<<"$(printf '%s' "$input" | python3 -c '
import json,sys; d=json.load(sys.stdin)
cwd=d.get("cwd") or d.get("workspace",{}).get("current_dir","")
m=d.get("model",{}).get("display_name","")
v=d.get("context_window",{}).get("used_percentage"); c=f"{v:.0f}%" if v is not None else "-"
print(cwd, m.replace(" ","_"), c)' 2>/dev/null)"
short(){ python3 -c "
import re,sys; t=open('$AD/registry/repos.yaml').read()
m=re.search(r'^  '+re.escape(sys.argv[1])+r':\n(?:    .*\n)*?    short: (\S+)', t, re.M); print(m.group(1) if m else sys.argv[1])" "$1"; }
Y=$'\e[33m'; G=$'\e[32m'; D=$'\e[2m'; B=$'\e[1m'; R=$'\e[0m'
case "$cwd" in
  "$AD"/lanes/*)
    # Line 1 is the WORKSTREAM. Line 2 lists every repo of it at the same weight — none is primary.
    # Where the shell sits is deliberately NOT shown: it reaches every repo either way, and naming one
    # read as a rank and sent sessions off trying to "fix" a pin that costs them nothing.
    rest=${cwd#"$AD"/lanes/}; id=${rest%%/*}
    items=(); n=0
    for d in "$AD/lanes/$id"/*/; do r=$(basename "$d"); [ -e "$d/.git" ] || continue
      n=$((n+1))
      dirty=$(lane_dirty_count "$d" 2>/dev/null || echo 0)
      up=$(lane_unpushed "$d"); [ "$up" = local ] && up=0; [ -z "$up" ] && up="?"
      s=$(short "$r")
      if [ "$dirty" != 0 ] || [ "$up" != 0 ]; then
        it="$s"; [ "$up" != 0 ] && it="$it ↑$up"; [ "$dirty" != 0 ] && it="$it ✎$dirty"
        items+=("$Y$it$R")
      else items+=("$D$s ✓$R"); fi
    done
    plural=""; [ "$n" = 1 ] || plural="s"
    printf '%s⧉ %s%s  %s%s repo%s · %s · ctx %s%s\n' "$B" "$id" "$R" "$D" "$n" "$plural" "${model//_/ }" "$ctx" "$R"
    printf '   %s' "$(IFS=·; echo "${items[*]}" | sed 's/·/ · /g')"
    ;;
  "$AD"/repos/*)
    printf '%s⚠ MIRROR (read-only) %s%s · %s' "$Y" "$(short "$(basename "$cwd")")" "$R" "${model//_/ }";;
  "$AD"*)
    n=$(grep -l '^status: active' "$AD"/registry/lanes/*.md 2>/dev/null | wc -l | tr -d ' ')
    printf '%s⌂ lane%s · %s active lanes · %s%s · ctx %s%s' "$B" "$R" "$n" "$D" "${model//_/ }" "$ctx" "$R";;
  *)
    br=$(git -C "$cwd" branch --show-current 2>/dev/null)
    printf '%s%s · %s · ctx %s' "$(basename "$cwd")" "${br:+@$br}" "${model//_/ }" "$ctx";;
esac

exit 0
