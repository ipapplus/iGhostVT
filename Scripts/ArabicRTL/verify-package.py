#!/usr/bin/env python3
"""Inspect a custom DEB in a temporary directory; never install or launch it."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import stat
import struct
import subprocess
import tarfile
import tempfile


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(package, flavor, source):
    expected_arch = {"roothide": "iphoneos-arm64e", "rootless": "iphoneos-arm64"}[flavor]
    prefix = "" if flavor == "roothide" else "var/jb"
    lock = json.loads((source / "Scripts/ArabicRTL/source-lock.json").read_text())
    metadata = {key: run("dpkg-deb", "-f", str(package), key) for key in ["Package", "Version", "Architecture", "Depends"]}
    require(metadata["Package"] == "wiki.qaq.ighostvt", "Package identity changed")
    require(metadata["Architecture"] == expected_arch, "Wrong package architecture")
    dependencies = {"".join(x.split()) for x in metadata["Depends"].split(",")}
    require(dependencies == {"firmware(>=15.0)", "uikittools", "launchctl", "shell-cmds"}, "Package dependencies changed")
    process = subprocess.Popen(["dpkg-deb", "--fsys-tarfile", str(package)], stdout=subprocess.PIPE)
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "Unsafe archive path")
            require(member.uid == 0 and member.gid == 0, "Unexpected package ownership")
            require(not any(x.startswith(".jbroot-") for x in path.parts), "Randomized jbroot path in archive")
    process.stdout.close()
    require(process.wait() == 0, "Cannot inspect package archive")
    result = {"metadata": metadata, "flavor": flavor, "binaries": {}}
    with tempfile.TemporaryDirectory(prefix="ighostvt-verify-") as directory:
        stage = Path(directory)
        subprocess.run(["dpkg-deb", "-R", str(package), str(stage)], check=True)
        root = stage / prefix
        app = root / "Applications/iGhostVT.app"
        info = plistlib.loads((app / "Info.plist").read_bytes())
        require(info["CFBundleIdentifier"] == "wiki.qaq.iGhostVT", "Bundle identity changed")
        require(info["CFBundleShortVersionString"] == metadata["Version"], "App/package version mismatch")
        require(int(info["CFBundleVersion"]) > 153, "Custom app build number was not increased")
        result["bundle"] = {k: info[k] for k in ["CFBundleIdentifier", "CFBundleShortVersionString", "CFBundleVersion"]}
        main = app / info["CFBundleExecutable"]
        binaries = [
            (main, "iGhostVT.entitlements"),
            (app / "ighostvt-cli", "iGhostVTCLI.entitlements"),
            (root / "usr/libexec/ighostvtd", "iGhostVTDaemon.entitlements"),
            (root / "usr/libexec/ighostvtd-io", "iGhostVTDaemon.entitlements"),
            (root / "usr/libexec/ighostvtd-remote", "iGhostVTRemote.entitlements"),
        ]
        widgets = list((app / "PlugIns").glob("*.appex"))
        require(bool(widgets), "Missing app extension")
        for widget in widgets:
            widget_info = plistlib.loads((widget / "Info.plist").read_bytes())
            binaries.append((widget / widget_info["CFBundleExecutable"], "iGhostVTWidgets.entitlements"))
        for binary, entitlement_name in binaries:
            data = binary.read_bytes()
            require(len(data) >= 32, "Empty executable")
            header = struct.unpack_from("<8I", data)
            require(header[0] == 0xFEEDFACF and header[1] == 0x0100000C, "Executable is not real arm64 Mach-O")
            require((header[2] & 0x00FFFFFF) == 0, "Unexpected Mach-O CPU subtype; architecture must not be relabeled")
            mode = stat.S_IMODE(binary.stat().st_mode)
            require(mode & 0o111 and not mode & 0o022, "Unsafe executable permissions")
            actual = plistlib.loads(subprocess.check_output(["ldid", "-e", str(binary)]))
            expected = plistlib.loads((source / "Packaging" / entitlement_name).read_bytes())
            require(actual == expected, "Entitlements changed: " + binary.name)
            libraries = run("otool", "-L", str(binary)).splitlines()[1:]
            if binary.name.startswith("ighostvtd") or binary.name == "ighostvt-cli":
                require(not any("libvroot" in x for x in libraries), "Unexpected daemon/client vroot dependency")
            result["binaries"][str(binary.relative_to(stage))] = {
                "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "mode": oct(mode), "mach_o_cpu_subtype": header[2], "libraries": libraries,
                "entitlements_match": True,
            }
        require(lock["binary_marker"].encode() in main.read_bytes(), "Final app lacks patched engine marker")
        provenance_files = list(app.rglob("ArabicRTLBuild.json"))
        require(len(provenance_files) == 1, "Missing or ambiguous RTL provenance resource")
        provenance = json.loads(provenance_files[0].read_text())
        for field in ["engine_baseline", "wrapper_commit", "rtl_implementation_commit", "engine_patch_sha256", "binary_marker"]:
            require(provenance[field] == lock[field], "RTL build provenance mismatch: " + field)
        result["rtl_provenance"] = provenance
        licenses = json.loads((app / "Licenses.json").read_text())
        require(any(x["name"] == "itijah" for x in licenses), "Missing itijah license notice")
        daemon_plist = root / "Library/LaunchDaemons/wiki.qaq.ighostvtd.plist"
        launch = plistlib.loads(daemon_plist.read_bytes())
        expected_program = ("/var/jb" if flavor == "rootless" else "") + "/usr/libexec/ighostvtd"
        require(launch["ProgramArguments"][0] == expected_program, "LaunchDaemon layout changed")
        require(stat.S_IMODE(daemon_plist.stat().st_mode) == 0o644, "Wrong LaunchDaemon permissions")
        require(os.readlink(root / "usr/bin/ighostvt-cli") == "../../Applications/iGhostVT.app/ighostvt-cli", "CLI symlink layout changed")
        for name in ["postinst", "prerm", "postrm"]:
            subprocess.run(["sh", "-n", str(stage / "DEBIAN" / name)], check=True)
    result.update(path=str(package), size=package.stat().st_size, sha256=hashlib.sha256(package.read_bytes()).hexdigest())
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--flavor", choices=["roothide", "rootless"], required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.package.resolve(), args.flavor, args.source.resolve())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ["path", "size", "sha256", "metadata"]}, indent=2))
