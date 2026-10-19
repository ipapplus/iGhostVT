#!/usr/bin/env python3
"""Create a CI-local dependency override for a verified, freshly rebuilt wrapper."""
import argparse
import json
from pathlib import Path
import plistlib
import re
import shutil


def integrate(app, wrapper, derived_data):
    if (wrapper / "Ghostty.ref").read_text().strip() != "1e9e14af5df14211892f5fc15fd21a49c7d94868":
        raise ValueError("Unexpected wrapper engine baseline")
    kit = wrapper / "BinaryTarget/GhosttyKit.xcframework"
    info = plistlib.loads((kit / "Info.plist").read_bytes())
    device = [x for x in info["AvailableLibraries"] if x["SupportedPlatform"] == "ios" and not x.get("SupportedPlatformVariant")]
    if len(device) != 1 or "arm64" not in device[0]["SupportedArchitectures"]:
        raise ValueError("Missing real iOS arm64 XCFramework slice")
    archive = kit / device[0]["LibraryIdentifier"] / device[0]["LibraryPath"]
    if not archive.is_file():
        raise ValueError("Device archive does not exist")
    if b"iGhostVT-ArabicRTL-coretext-itijah-0.2.1-20261019" not in archive.read_bytes():
        raise ValueError("Rebuilt archive lacks the custom RTL engine marker")

    project = app / "iGhostVT.xcodeproj/project.pbxproj"
    text = project.read_text()
    old = '''\t\tAA0000000000000000000A01 /* XCRemoteSwiftPackageReference "libghostty-spm" */ = {
\t\t\tisa = XCRemoteSwiftPackageReference;
\t\t\trepositoryURL = "https://github.com/Lakr233/libghostty-spm";
\t\t\trequirement = {
\t\t\t\tkind = upToNextMajorVersion;
\t\t\t\tminimumVersion = 2.2.2026101901;
\t\t\t};
\t\t};'''
    new = '''\t\tAA0000000000000000000A01 /* XCLocalSwiftPackageReference "libghostty-spm" */ = {
\t\t\tisa = XCLocalSwiftPackageReference;
\t\t\trelativePath = ''' + json.dumps(str(wrapper)) + ''';
\t\t};'''
    if text.count(old) != 1:
        raise ValueError("Pinned remote package reference changed unexpectedly")
    text = text.replace(old, new)
    text = text.replace('/* XCRemoteSwiftPackageReference "libghostty-spm" */', '/* XCLocalSwiftPackageReference "libghostty-spm" */')
    for config in ["AA0000000000000000000B03", "AA0000000000000000000B04"]:
        pattern = r"(?m)^\t\t" + config + r" /\*.*?^\t\t};"
        matches = list(re.finditer(pattern, text, flags=re.S | re.M))
        if len(matches) != 1:
            raise ValueError("App build configuration changed unexpectedly")
        match = matches[0]
        block = match.group()
        if "PRODUCT_BUNDLE_IDENTIFIER = wiki.qaq.iGhostVT;" not in block or block.count("ActivityKit,") != 1:
            raise ValueError("Unexpected target or linker settings")
        block = block.replace("ActivityKit,", 'ActivityKit,\n\t\t\t\t\t"-Wl,-u,_ghostty_arabic_rtl_build_id",')
        block = block.replace("PRODUCT_BUNDLE_IDENTIFIER =", "LD_GENERATE_MAP_FILE = YES;\n\t\t\t\tPRODUCT_BUNDLE_IDENTIFIER =")
        text = text[:match.start()] + block + text[match.end():]
    project.write_text(text)

    checkouts = derived_data / "SourcePackages/checkouts"
    checkouts.mkdir(parents=True, exist_ok=True)
    link = checkouts / "libghostty-spm"
    if link.exists() or link.is_symlink():
        if link.resolve() != wrapper:
            raise ValueError("Refusing to replace a different package checkout")
    else:
        link.symlink_to(wrapper, target_is_directory=True)

    notices = [
        ("libghostty-spm-local", "libghostty-spm", "LICENSE", "https://github.com/Lakr233/libghostty-spm", "dfe0cb03415cb2371d71ed46cd4db0614bef84eb"),
        ("iterm2-color-schemes", "iTerm2 Color Schemes", "Sources/GhosttyTheme/LICENSE", "https://github.com/mbadolato/iTerm2-Color-Schemes", None),
        ("bash-preexec", "bash-preexec", "Sources/GhosttyTerminal/Resources/Ghostty/shell-integration/bash/LICENSE-bash-preexec.md", "https://github.com/rcaloras/bash-preexec", None),
    ]
    for folder, name, source, url, version in notices:
        target = app / "Licenses" / folder
        target.mkdir(exist_ok=True)
        shutil.copyfile(wrapper / source, target / "LICENSE")
        (target / "notice.json").write_text(json.dumps({"name": name, "url": url, "version": version}, indent=2) + "\n")
    return {"wrapper": str(wrapper), "device_archive": str(archive), "project": str(project)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--wrapper", required=True, type=Path)
    parser.add_argument("--derived-data", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(integrate(args.app.resolve(), args.wrapper.resolve(), args.derived_data.resolve()), indent=2))
