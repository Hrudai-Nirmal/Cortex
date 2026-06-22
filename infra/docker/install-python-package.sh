#!/usr/bin/env sh
# Install Cortex Python dependencies while forcing the intended PyTorch wheel channel first.

set -eu

projectInstallTarget="${1:-.[dev,ingestion]}"
torchWheelIndexUrl="${CORTEX_PACKAGE_PYTORCH_WHEEL_INDEX_URL:-}"
torchPreinstallPackages="${CORTEX_PACKAGE_PYTORCH_PREINSTALL:-torch torchvision}"

if [ -n "$torchWheelIndexUrl" ] && [ -n "$torchPreinstallPackages" ]; then
  echo "Preinstalling PyTorch packages from ${torchWheelIndexUrl}" >&2
  # shellcheck disable=SC2086
  pip install --no-cache-dir --index-url "$torchWheelIndexUrl" $torchPreinstallPackages
  pip install --no-cache-dir --extra-index-url "$torchWheelIndexUrl" -e "$projectInstallTarget"
else
  pip install --no-cache-dir -e "$projectInstallTarget"
fi
