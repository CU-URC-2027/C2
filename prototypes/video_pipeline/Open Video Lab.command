#!/bin/zsh
set -e
cd -- "${0:A:h}"
if command -v uv >/dev/null 2>&1; then
  video_lab_uv="$(command -v uv)"
elif [[ -x "$HOME/.local/bin/uv" ]]; then
  video_lab_uv="$HOME/.local/bin/uv"
else
  print "Install uv from https://docs.astral.sh/uv/ before using this launcher."
  read -k 1
  exit 1
fi
"$video_lab_uv" sync --frozen
"$video_lab_uv" run python dev.py --open
