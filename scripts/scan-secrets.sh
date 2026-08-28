#!/usr/bin/env bash
# Secret scanner. Exit 0 = clean, 1 = secret found, 2 = could not run.
#
# Exit 2 matters as much as exit 1: a scanner that finds no files must not
# report a pass. "Clean" and "did not run" look identical unless you separate
# them, and a scanner nobody has watched fail is decoration.
#
# The patterns below are written as AIz[a] rather than AIza so this file does
# not match itself. That is deliberate — do not "fix" it.

set -uo pipefail

cd "$(dirname "$0")/.." || { echo "ERROR: cannot reach project root"; exit 2; }

PRUNE=( -name .git -o -name .venv -o -name node_modules -o -name __pycache__ \
        -o -name .pytest_cache -o -name .ruff_cache )

mapfile -t FILES < <(find . \( "${PRUNE[@]}" \) -prune -o -type f -print 2>/dev/null)

COUNT=${#FILES[@]}
if [ "$COUNT" -eq 0 ]; then
  echo "ERROR: scanned 0 files. Refusing to report a pass."
  exit 2
fi

# pattern|human-readable name
PATTERNS=(
  'AIz[a][0-9A-Za-z_-]{35}|Google API key'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----|PEM private key'
  '"private[_]key"[[:space:]]*:|service-account private_key field'
  'sk-[A-Za-z0-9]{20,}|sk- prefixed API token'
)

HITS=0
for entry in "${PATTERNS[@]}"; do
  pattern="${entry%%|*}"
  label="${entry##*|}"
  if matches=$(grep -rInE --binary-files=without-match "$pattern" "${FILES[@]}" 2>/dev/null); then
    echo "FOUND — $label:"
    echo "$matches" | sed 's/^/    /'
    HITS=$((HITS + 1))
  fi
done

echo "scanned $COUNT files"

if [ "$HITS" -gt 0 ]; then
  echo "FAILED — $HITS secret pattern(s) matched."
  exit 1
fi

echo "PASSED — no secret patterns matched."
exit 0
