#!/usr/bin/env bash
# Put floodgate on your PATH by appending a line to ~/.bashrc — but only once.
set -euo pipefail

# Directory holding this script (and the floodgate executable next to it).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="${HOME}/.bashrc"
LINE="export PATH=\"\$PATH:${DIR}\""

if [ -f "$BASHRC" ] && grep -qF "$DIR" "$BASHRC"; then
    echo "floodgate already on your PATH via $BASHRC — nothing to do."
    exit 0
fi

printf '\n# Added by floodgate install.sh\n%s\n' "$LINE" >> "$BASHRC"
echo "Added floodgate to your PATH in $BASHRC."
echo "Run 'source $BASHRC' (or open a new shell), then try: floodgate --help"
echo "Note: floodgate needs diffkit (structured-diff, filter-diff) on your PATH too."
