#!/usr/bin/env bash
# Stage the exact MAME 0.287 snap payload without replacing the installed snap.
set -euo pipefail

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
stage_root=${1:-$project_root/build/toolchain/mame-4339-recovery}
snap_file=$stage_root/mame_4339.snap
payload_root=$stage_root/root
payload=$payload_root/mame
expected_sha=297843036f728695878300f3bd9949122907cd83bfd6d501875e9a49cd950c6f

mkdir -p "$stage_root"
if [[ ! -f "$snap_file" ]]; then
  snap download mame --revision=4339 --target-directory="$stage_root"
fi
if [[ ! -f "$payload" ]]; then
  if [[ -e "$payload_root" ]]; then
    echo "refusing to overwrite incomplete payload directory: $payload_root" >&2
    exit 2
  fi
  unsquashfs -d "$payload_root" "$snap_file"
fi

observed_sha=$(sha256sum "$payload" | awk '{print $1}')
if [[ "$observed_sha" != "$expected_sha" ]]; then
  echo "pinned MAME payload hash mismatch: $observed_sha != $expected_sha" >&2
  exit 2
fi

version=$("$project_root/tools/mame_0287_exec.sh" -version)
if [[ "$version" != "0.287 (mame0287)" ]]; then
  echo "pinned MAME version mismatch: $version" >&2
  exit 2
fi

printf '%s\n' "MAME 0.287 staged: $payload" "SHA-256: $observed_sha"
