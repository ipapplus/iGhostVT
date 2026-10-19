#!/usr/bin/env bash
set -Eeuo pipefail
work="${GITHUB_WORKSPACE:?}"
app="$work/app"
control="$work/integration/Scripts/ArabicRTL"
output="$work/deliverables"
cd "$app"
make deb-rootless DERIVED_DATA="${RUNNER_TEMP:?}/ighostvt-arabic-deriveddata" 2>&1 | tee "$work/evidence/deb-rootless.log"
package="$app/build/Packages/wiki.qaq.ighostvt_1.6.16_iphoneos-arm64.deb"
python3 "$control/verify-package.py" "$package" --flavor rootless --source "$app" --output "$work/evidence/rootless-verification.json"
cp "$package" "$work/evidence/rootless-verification.json" "$output/"
cd "$output"
shasum -a 256 *.deb *.xcframework.zip source-lock.json engine-port.patch ArabicRTLBuild.json > SHA256SUMS
shasum -a 256 -c SHA256SUMS
