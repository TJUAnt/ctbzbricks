#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PROJECT_ROOT="$(cd "${GO_ROOT}/.." && pwd)"
VERSION="${GLTFPACK_VERSION:-v1.2}"
INSTALL_DIR="${PROJECT_ROOT}/.tools/meshoptimizer-${VERSION}"
ARCHIVE="${TMPDIR:-/tmp}/gltfpack-${VERSION}-macos.zip"
DOWNLOAD_URL="https://github.com/zeux/meshoptimizer/releases/download/${VERSION}/gltfpack-macos.zip"

# 官方 release 的原生二进制固定到明确版本；升级时修改 GLTFPACK_VERSION 并重新执行该脚本。
mkdir -p "${INSTALL_DIR}"
curl --fail --http1.1 --location --retry 3 --retry-all-errors --output "${ARCHIVE}" "${DOWNLOAD_URL}"
unzip -o "${ARCHIVE}" -d "${INSTALL_DIR}"
gltfpack_path="$(find "${INSTALL_DIR}" -type f -name gltfpack -print -quit)"
if [[ -z "${gltfpack_path}" ]]; then
  echo "error: gltfpack binary was not present in the official archive" >&2
  exit 1
fi
chmod +x "${gltfpack_path}"
"${gltfpack_path}" -h >/dev/null
printf '%s\n' "${gltfpack_path}"
