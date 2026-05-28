#!/usr/bin/env bash
# Put lean-infoview-cors on your PATH by appending a line to ~/.bashrc — but only once.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASHRC="${HOME}/.bashrc"
LINE="export PATH=\"\$PATH:${DIR}\""

if [ -f "$BASHRC" ] && grep -qF "$DIR" "$BASHRC"; then
    echo "lean-infoview-cors already on your PATH via $BASHRC — nothing to do."
    exit 0
fi

printf '\n# Added by lean-infoview-cors install.sh\n%s\n' "$LINE" >> "$BASHRC"
echo "Added lean-infoview-cors to your PATH in $BASHRC."
echo "Run 'source $BASHRC' (or open a new shell), then try: lean-infoview-cors --status"
