#!/usr/bin/env bash
# Execute the retained MAME 0.287 payload from its mounted or extracted snap.
# The MCP launcher cannot pass the required dynamic-library path itself.
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
expected_sha=297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f

if [[ -n "${SUPERMN_MAME_EXE:-}" ]]; then
  mame_exe=$SUPERMN_MAME_EXE
elif [[ -f /snap/mame/4339/mame ]]; then
  mame_exe=/snap/mame/4339/mame
elif [[ -f "$project_root/build/toolchain/mame-4339-recovery/root/mame" ]]; then
  mame_exe=$project_root/build/toolchain/mame-4339-recovery/root/mame
elif [[ -f /tmp/mame-4339-recovery/root/mame ]]; then
  mame_exe=/tmp/mame-4339-recovery/root/mame
else
  echo "missing pinned MAME 0.287 payload; run tools/stage_mame_0287.sh" >&2
  exit 2
fi

observed_sha=$(sha256sum "$mame_exe" | awk '{print $1}')
if [[ "$observed_sha" != "$expected_sha" ]]; then
  echo "pinned MAME payload hash mismatch: $observed_sha != $expected_sha" >&2
  exit 2
fi

mame_root=$(dirname "$mame_exe")
export LD_LIBRARY_PATH="$mame_root/lib:$mame_root/usr/lib:$mame_root/lib/x86_64-linux-gnu:$mame_root/usr/lib/x86_64-linux-gnu:$mame_root/usr/lib/x86_64-linux-gnu/pulseaudio:/snap/gnome-42-2204/263/lib:/snap/gnome-42-2204/263/usr/lib:/snap/gnome-42-2204/263/usr/lib/x86_64-linux-gnu:/snap/gnome-42-2204/263/usr/lib/x86_64-linux-gnu/pulseaudio${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
exec "$mame_exe" "$@"
