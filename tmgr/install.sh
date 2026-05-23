#!/usr/bin/env bash
# Put tmgr on your PATH by appending a line to ~/.bashrc — but only once.
set -euo pipefail

# Directory holding this script (and the tmgr executable next to it).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="${HOME}/.bashrc"
LINE="export PATH=\"\$PATH:${DIR}\""

if [ -f "$BASHRC" ] && grep -qF "$DIR" "$BASHRC"; then
    echo "tmgr already on your PATH via $BASHRC — nothing to do."
    exit 0
fi

printf '\n# Added by tmgr install.sh\n%s\n' "$LINE" >> "$BASHRC"
echo "Added tmgr to your PATH in $BASHRC."
echo "Run 'source $BASHRC' (or open a new shell), then try: tmgr --help"
