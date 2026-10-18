#!/usr/bin/env bash
# The secret-name list that lane park / lane done use (scripts/gitstate.sh lane_secret_paths) must
# be the guard's own list (SECRET_FILE / SAFE_ENV_SUFFIX in scripts/hooks/guard.py). It cannot import
# guard.py, so this test is what keeps the two from drifting apart.
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

extract(){ # <file> <var-name-regex> -> the r"..." pattern text
  python3 - "$1" "$2" <<'PY'
import re, sys
t = open(sys.argv[1]).read()
m = re.search(sys.argv[2] + r'\s*=\s*re\.compile\(r"((?:[^"\\]|\\.)*)"', t)
print(m.group(1) if m else "NOT-FOUND")
PY
}
g1=$(extract "$PRODUCT/scripts/hooks/guard.py" 'SECRET_FILE')
g2=$(extract "$PRODUCT/scripts/hooks/guard.py" 'SAFE_ENV_SUFFIX')
l1=$(extract "$PRODUCT/scripts/gitstate.sh" 'rx')
l2=$(extract "$PRODUCT/scripts/gitstate.sh" 'safe')
assert_eq "SECRET_FILE pattern is the guard's" "$g1" "$l1"
assert_eq "SAFE_ENV_SUFFIX pattern is the guard's" "$g2" "$l2"
# the board's copies (scripts/board/server.py) must be the same text too (T2)
b1=$(extract "$PRODUCT/scripts/board/server.py" 'SECRET')
b2=$(extract "$PRODUCT/scripts/board/server.py" 'SAFE_SUFFIX')
assert_eq "board SECRET pattern is the guard's" "$g1" "$b1"
assert_eq "board SAFE_SUFFIX pattern is the guard's" "$g2" "$b2"
assert "the pattern was really found (not NOT-FOUND)" test "$b1" != NOT-FOUND

T=$(mk_tmp); SANDBOXES="$SANDBOXES $T"
source "$PRODUCT/scripts/gitstate.sh"
filter(){ printf '%s\0' "$@" | lane_secret_paths "$T" | tr '\0' '\n'; }
secrets=".env .env.local .ENV sub/dir/.env.production server.pem a/b/deploy.key x.p12 y.pfx gcp-credentials.json secrets.yaml secret.toml secrets.json id_rsa id_ed25519 id_ecdsa id_dsa .ssh/id_rsa ID_RSA Id_Ed25519 .netrc .npmrc .pgpass .git-credentials .htpasswd .NETRC AuthKey.p8 release.jks my.keystore vault.kdbx cert.pfx cert.p12 service-account.json service-account-prod.json Service-Account.JSON credentials.json aws-credentials.json CREDENTIALS.JSON"
for f in $secrets; do
  assert_eq "$f is a secret name" "$f" "$(filter "$f")"
done
for f in id_rsa.pub id_ed25519.pub id_rsa.pub.bak my_id_rsa.txt netrc npmrc.txt service-account.txt service-accounts.yaml credentials.txt .htpasswd.example id_rsa.example .env.example .env.sample .env.template .env.dist README.md environment.py keyboard.py monkey.txt src/envelope.js docs/key-concepts.md notes.txt; do
  assert_eq "$f is not a secret name" "" "$(filter "$f")"
done
ln -s "$T/target" "$T/link.env"; : > "$T/real.env"; ln -s "$T/target" "$T/.env"
assert_eq "--skip-links drops a symlinked .env" "" "$(printf '.env\0' | lane_secret_paths "$T" --skip-links | tr '\0' '\n')"
printf 'k\n' > "$T/.env.local"
assert_eq "--skip-links keeps a real file" ".env.local" "$(printf '.env.local\0' | lane_secret_paths "$T" --skip-links | tr '\0' '\n')"
assert_eq "an embedded newline does not hide a secret name" "$(printf '\303\251\n.env')" "$(filter "$(printf '\303\251\n.env')")"
assert_eq "paths with spaces survive" "my dir/.env" "$(filter "my dir/.env")"

echo "-- lane park never commits the key / credential file names (untracked and tracked-modified)"
new_sandbox; init_plane >/dev/null 2>&1
make_remote_repo kz noignore; add_repo kz
WT(){ echo "$PLANE/lanes/$1/$2"; }
KEYS="id_rsa id_ed25519 id_ecdsa id_dsa .netrc .npmrc .pgpass .git-credentials .htpasswd auth.p8 rel.jks my.keystore v.kdbx c.pfx c.p12 service-account.json service-account-x.json credentials.json d/ID_RSA d/.NETRC"
lane start K1 kz; W="$(WT K1 kz)"; mkdir -p "$W/d"
for k in $KEYS; do printf 'S-%s\n' "$k" > "$W/$k"; done
printf 'pub\n' > "$W/id_rsa.pub"; printf 'n\n' > "$W/notes.txt"
lane park K1 "untracked key files"
assert_eq "park exits 0 (untracked keys)" 0 "$RC"
files=$(git -C "$W" show --name-only --format= HEAD)
assert_contains "wip commit has notes.txt" "$files" "notes.txt"
assert_contains "id_rsa.pub is not a secret: it is committed" "$files" "id_rsa.pub"
for k in $KEYS; do
  case "
$files
" in *"
$k
"*) bad "park committed untracked $k" ;; *) ok "park left untracked $k out" ;; esac
done
lane start K2 kz; W2="$(WT K2 kz)"; mkdir -p "$W2/d"
for k in $KEYS; do printf 'v1\n' > "$W2/$k"; done
git -C "$W2" add -f -- $KEYS && git -C "$W2" commit -q -m "tracked keys"
for k in $KEYS; do printf 'v2-%s\n' "$k" >> "$W2/$k"; done
printf 'n\n' > "$W2/notes.txt"
lane park K2 "tracked-modified key files"
files=$(git -C "$W2" show --name-only --format= HEAD)
assert_contains "wip commit (tracked case) has notes.txt" "$files" "notes.txt"
for k in $KEYS; do
  case "
$files
" in *"
$k
"*) bad "park committed modified tracked $k" ;; *) ok "park left modified tracked $k out" ;; esac
done

finish
