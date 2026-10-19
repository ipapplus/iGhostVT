#!/usr/bin/env bash
set -Eeuo pipefail

work="${GITHUB_WORKSPACE:?GitHub Actions workspace is required}"
engine="$work/engine"
wrapper="$work/wrapper"
app="$work/app"
control="$work/integration/Scripts/ArabicRTL"
evidence="$work/evidence"
output="$work/deliverables"
export ARABIC_RTL_DERIVED_DATA="${RUNNER_TEMP:?}/ighostvt-arabic-deriveddata"
mkdir -p "$output" "$evidence"

python3 - "$control" <<'PYLOCK'
from pathlib import Path
import hashlib, json, sys
root = Path(sys.argv[1])
lock = json.loads((root / "source-lock.json").read_text())
assert hashlib.sha256((root / "engine-port.patch").read_bytes()).hexdigest() == lock["engine_patch_sha256"]
PYLOCK

python3 "$control/fetch-conformance-data.py" "$engine/pkg/itijah/testdata" | tee "$evidence/unicode-fixtures.json"
cd "$engine"
zig build test --summary all -Dapp-runtime=none -Demit-macos-app=false -Dcustom-shaders=false -Dinspector=false -Di18n=false -Dsentry=false -Dfont-backend=coretext_harfbuzz -Dtest-filter=shape 2>&1 | tee "$evidence/rtl-harfbuzz-shapers.log"
zig build test --summary all -Dapp-runtime=none -Demit-macos-app=false -Dcustom-shaders=false -Dinspector=false -Di18n=false -Dsentry=false -Dfont-backend=coretext -Dtest-filter=conformance -Dbidi-conformance-data=true -Doptimize=ReleaseSafe 2>&1 | tee "$evidence/bidi-conformance.log"

export ZIG_BUILD_EXTRA_ARGS="-Dfont-backend=coretext"
cd "$wrapper"
./Script/build-platform.sh "$engine" macos "$wrapper/build/rtl-artifacts" 2>&1 | tee "$evidence/rtl-macos-build.log"
./Script/build-ghostty.sh "$engine" aarch64-ios "$wrapper/build/rtl-artifacts/iphoneos" 2>&1 | tee "$evidence/rtl-ios-build.log"
./Script/merge-xcframework.sh "$wrapper/build/rtl-artifacts" "$wrapper/BinaryTarget/GhosttyKit.xcframework" "$wrapper/build/ArabicGhosttyKit.xcframework.zip" 2>&1 | tee "$evidence/rtl-xcframework.log"
nm -g -U -arch arm64 "$wrapper/build/rtl-artifacts/iphoneos/lib/libghostty.a" > "$evidence/rtl-device-symbols.log"
python3 - "$wrapper/build/rtl-artifacts/iphoneos/lib/libghostty.a" "$evidence/rtl-device-symbols.log" <<'PYSYMBOLS'
from pathlib import Path
import sys
archive = Path(sys.argv[1]).read_bytes()
symbols = Path(sys.argv[2]).read_text()
for name in ["_ghostty_init", "_ghostty_surface_new", "_ghostty_surface_write_buffer", "_ghostty_arabic_rtl_build_id"]:
    assert name in symbols, name
assert b"iGhostVT-ArabicRTL-coretext-itijah-0.2.1-20261019" in archive
PYSYMBOLS
cp Package.local.swift Package.swift
swift test 2>&1 | tee "$evidence/rtl-swift-test.log"
xcodebuild -scheme GhosttyTerminal -destination 'generic/platform=iOS' CODE_SIGNING_ALLOWED=NO build 2>&1 | tee "$evidence/rtl-wrapper-ios-build.log"

cp -R "$control" "$app/Scripts/"
cp -R "$work/integration/Licenses/itijah" "$app/Licenses/"
python3 "$control/integrate-local-wrapper.py" --app "$app" --wrapper "$wrapper" --derived-data "$ARABIC_RTL_DERIVED_DATA" | tee "$evidence/local-wrapper-integration.json"
cd "$app"
make set-version VERSION=1.6.16 BUILD=154
make check 2>&1 | tee "$evidence/rtl-make-check.log"
make test 2>&1 | tee "$evidence/rtl-make-test.log"
python3 - "$control/source-lock.json" "$app/iGhostVT/Resources/ArabicRTLBuild.json" "$wrapper/build/ArabicGhosttyKit.xcframework.zip" <<'PYPROVENANCE'
from pathlib import Path
import hashlib, json, os, subprocess, sys
lock = json.loads(Path(sys.argv[1]).read_text())
lock.update(integration_commit=os.environ["GITHUB_SHA"], workflow_url="https://github.com/" + os.environ["GITHUB_REPOSITORY"] + "/actions/runs/" + os.environ["GITHUB_RUN_ID"], xcode_version=subprocess.check_output(["xcodebuild", "-version"], text=True).strip(), swift_version=subprocess.check_output(["swift", "--version"], text=True).strip(), xcframework_sha256=hashlib.sha256(Path(sys.argv[3]).read_bytes()).hexdigest(), app_version="1.6.16", app_build="154")
Path(sys.argv[2]).write_text(json.dumps(lock, indent=2) + "\n")
PYPROVENANCE
make deb-roothide DERIVED_DATA="$ARABIC_RTL_DERIVED_DATA" 2>&1 | tee "$evidence/deb-roothide.log"
roothide="$app/build/Packages/wiki.qaq.ighostvt_1.6.16_iphoneos-arm64e.deb"
python3 "$control/verify-package.py" "$roothide" --flavor roothide --source "$app" --output "$evidence/roothide-verification.json"
cp "$roothide" "$output/"
cp "$wrapper/build/ArabicGhosttyKit.xcframework.zip" "$output/"
cp "$control/source-lock.json" "$control/engine-port.patch" "$output/"
cp "$app/iGhostVT/Resources/ArabicRTLBuild.json" "$output/"
cp "$evidence/roothide-verification.json" "$output/"
git diff --binary HEAD > "$evidence/app-effective.patch"
cd "$output"
shasum -a 256 *.deb *.xcframework.zip source-lock.json engine-port.patch ArabicRTLBuild.json > SHA256SUMS
shasum -a 256 -c SHA256SUMS
