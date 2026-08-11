#!/usr/bin/env bash
# Launch the project-approved Nexen MCP build with its pinned .NET 10 runtime.
# Tools using mesen_mcp spawn this executable directly and therefore do not
# inherit a shell-specific DOTNET_ROOT setup.
set -euo pipefail

exec env DOTNET_ROOT=/home/chad/.dotnet10 \
  /mnt/sdc1/Nexen-r5-20260712/bin/linux-x64/Release/mcp-safe-checkpoint-publish/Nexen \
  "$@"
