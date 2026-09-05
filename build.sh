#!/usr/bin/env bash
# SPDX-License-Identifier: CC0-1.0
#
# Rebuild the exported site from your own copy of Hypnospace Outlaw.
#
#   ./build.sh /path/to/Hypnospace Outlaw      # install root, or its data/ dir
#
# No game asset is redistributed with this repository; this script reads the
# copy you already own and writes the export into ./site.

set -euo pipefail

usage() {
  cat <<'USAGE'
usage: ./build.sh <path-to-Hypnospace-Outlaw> [options]

  <path>            the game's install directory, or its data/ subdirectory

  --out DIR         where to write the site        (default: ./site)
  --base-url URL    where the site will be served, e.g. https://example.com/hsp
                    (fills in og:url and og:image so links preview properly)
  --copy-assets     copy referenced art/audio into the export instead of
                    symlinking the game's data/ (makes it movable/servable,
                    at the cost of disk)
  --no-music        skip the .hsm tracker render (needs ffmpeg + numpy)
  --pages P...      convert only these top-level dirs (default: hs hsa hsb hsc ex)

Typical install locations:
  Steam (Linux)     ~/.steam/steam/steamapps/common/Hypnospace Outlaw
  Steam (macOS)     ~/Library/Application Support/Steam/steamapps/common/Hypnospace Outlaw
  Steam (Windows)   C:\Program Files (x86)\Steam\steamapps\common\Hypnospace Outlaw
  GOG via Heroic    ~/Games/Heroic/Hypnospace Outlaw
  itch.io app       ~/.config/itch/apps/hypnospace-outlaw
USAGE
}

[ $# -ge 1 ] || { usage; exit 2; }
case "$1" in -h|--help) usage; exit 0;; esac

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
game="$1"; shift

out="$here/site"
music=1
conv_extra=()

while [ $# -gt 0 ]; do
  case "$1" in
    --out)          out="$2"; shift 2;;
    --copy-assets)  conv_extra+=(--copy-assets); shift;;
    --base-url)     conv_extra+=(--base-url "$2"); shift 2;;
    --no-music)     music=0; shift;;
    --pages)        shift; conv_extra+=(--pages)
                    while [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; do conv_extra+=("$1"); shift; done;;
    -h|--help)      usage; exit 0;;
    *)              echo "build.sh: unknown option '$1'" >&2; usage; exit 2;;
  esac
done

# ---------------------------------------------------------------- locate data/
# Accept either the install root or data/ itself, so it does not matter which
# one the user happened to point at.
if   [ -d "$game/data/hs" ]; then data="$game/data"
elif [ -d "$game/hs" ];      then data="$game"
else
  echo "build.sh: '$game' does not look like a Hypnospace Outlaw install." >&2
  echo "  Expected to find a data/ directory containing hs/, images/, misc/." >&2
  echo "  Run './build.sh --help' for the usual install locations." >&2
  exit 1
fi
data="$(cd "$data" && pwd)"

for need in hs images misc; do
  [ -d "$data/$need" ] || { echo "build.sh: '$data' is missing $need/ -- incomplete install?" >&2; exit 1; }
done
echo "game data: $data"

# ------------------------------------------------------------------ toolchain
command -v python3 >/dev/null || { echo "build.sh: python3 not found." >&2; exit 1; }

if [ "$music" = 1 ]; then
  miss=()
  command -v ffmpeg >/dev/null || miss+=("ffmpeg")
  python3 -c 'import numpy' 2>/dev/null || miss+=("numpy (pip install numpy)")
  if [ ${#miss[@]} -gt 0 ]; then
    echo "build.sh: skipping tracker music -- missing: ${miss[*]}" >&2
    echo "          install them and re-run, or pass --no-music to silence this." >&2
    music=0
  fi
fi

mkdir -p "$out"
out="$(cd "$out" && pwd)"

# --------------------------------------------------------------------- render
# Tracker modules first: hspconv.py reads the manifest this leaves behind, so
# that pages backed by a .hsm come out with a real <audio> src and a title.
if [ "$music" = 1 ]; then
  echo
  echo "== rendering .hsm tracker music (a couple of minutes) =="
  python3 "$here/tools/hsmrender.py" --data "$data" --out "$out/media/hsm"
fi

echo
echo "== converting pages =="
python3 "$here/tools/hspconv.py" --data "$data" --out "$out" ${conv_extra[@]+"${conv_extra[@]}"}

echo
echo "== auditing =="
python3 "$here/tools/hspaudit.py" --site "$out" --data "$data" || true

echo
echo "done -- open $out/index.html"
