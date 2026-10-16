"""Build installable Ventris packages for the current OS.

    python packaging/build.py            # build for this machine
    python packaging/build.py --smoke    # also start the built app once to check it runs

Output goes to dist/release/:
  Windows  Ventris-<ver>-windows-<arch>.zip (portable) and, if Inno Setup is
           installed, Ventris-<ver>-windows-<arch>-setup.exe
  macOS    Ventris-<ver>-macos-<arch>.dmg
  Linux    Ventris-<ver>-linux-<arch>.AppImage (needs appimagetool; downloaded if missing)
Requires: pip install pyinstaller pillow
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ventris import APP_ID, APP_NAME, __version__  # noqa: E402

DIST = ROOT / "dist"
RELEASE = DIST / "release"
ICON_PNG = ROOT / "ventris" / "assets" / "ventris.png"
APPIMAGETOOL_URL = ("https://github.com/AppImage/appimagetool/releases/download/continuous/"
                    "appimagetool-{arch}.AppImage")


def arch() -> str:
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x86_64" if sys.platform != "win32" else "x64",
            "arm64": "arm64", "aarch64": "aarch64"}.get(machine, machine)


def run(cmd: list, **kw) -> None:
    print("+", " ".join(str(c) for c in cmd), flush=True)
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def pyinstaller() -> Path:
    sep = ";" if sys.platform == "win32" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
           "--name", APP_NAME, "--icon", ICON_PNG,
           "--add-data", f"{ROOT / 'ventris' / 'assets'}{sep}ventris/assets",
           "--distpath", DIST, "--workpath", ROOT / "build", "--specpath", ROOT / "build"]
    if sys.platform == "darwin":
        cmd += ["--osx-bundle-identifier", APP_ID]
    run(cmd + [ROOT / "packaging" / "launcher.py"], cwd=ROOT)
    return DIST / (f"{APP_NAME}.app" if sys.platform == "darwin" else APP_NAME)


def smoke_test(executable: Path) -> None:
    env = dict(os.environ, VENTRIS_SMOKE_TEST="1", QT_QPA_PLATFORM="offscreen",
               # AppImages: run without FUSE (CI) and bypass AppImageLauncher if installed
               APPIMAGE_EXTRACT_AND_RUN="1", APPIMAGELAUNCHER_DISABLE="1")
    sample = ROOT / "tests" / "fixtures" / "prusa_mk4s_cube.bgcode"
    result = subprocess.run([str(executable), str(sample)], env=env, capture_output=True,
                            text=True, timeout=120)
    print(result.stdout, result.stderr, sep="\n")
    if result.returncode != 0 or "started OK" not in result.stdout:
        raise SystemExit(f"smoke test failed (exit {result.returncode})")
    print("smoke test passed")


# ---------------------------------------------------------------- per-OS packaging


def package_windows(app_dir: Path) -> list[Path]:
    name = f"{APP_NAME}-{__version__}-windows-{arch()}"
    outputs = [Path(shutil.make_archive(str(RELEASE / name), "zip", DIST, APP_NAME))]
    iscc = shutil.which("iscc") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if Path(iscc).exists():
        run([iscc, f"/DAppVersion={__version__}", f"/DSourceDir={app_dir}",
             f"/DOutputDir={RELEASE}", f"/DOutputName={name}-setup",
             f"/DIconFile={DIST / 'ventris.ico'}", ROOT / "packaging" / "ventris.iss"])
        outputs.append(RELEASE / f"{name}-setup.exe")
    else:
        print("Inno Setup not found; skipping the installer (zip only)")
    return outputs


def package_macos(app: Path) -> list[Path]:
    info_path = app / "Contents" / "Info.plist"
    info = plistlib.loads(info_path.read_bytes())
    info.update({
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "G-code",
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Alternate",
            "CFBundleTypeExtensions": ["gcode", "gco", "bgcode", "3mf"],
        }],
    })
    info_path.write_bytes(plistlib.dumps(info))
    # PyInstaller signs ad hoc; re-sign after editing Info.plist so the bundle stays valid.
    run(["codesign", "--force", "--deep", "--sign", "-", app])
    staging = DIST / "dmg"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    shutil.copytree(app, staging / app.name, symlinks=True)
    os.symlink("/Applications", staging / "Applications")
    dmg = RELEASE / f"{APP_NAME}-{__version__}-macos-{arch()}.dmg"
    run(["hdiutil", "create", "-volname", APP_NAME, "-srcfolder", staging, "-ov",
         "-format", "UDZO", dmg])
    return [dmg]


def package_linux(app_dir: Path) -> list[Path]:
    appdir = DIST / f"{APP_NAME}.AppDir"
    shutil.rmtree(appdir, ignore_errors=True)
    shutil.copytree(app_dir, appdir / "usr" / "lib" / "ventris", symlinks=True)
    (appdir / "AppRun").write_text(
        '#!/bin/sh\nHERE="$(dirname "$(readlink -f "$0")")"\n'
        'exec "$HERE/usr/lib/ventris/Ventris" "$@"\n')
    (appdir / "AppRun").chmod(0o755)
    shutil.copy(ICON_PNG, appdir / "ventris.png")
    (appdir / "ventris.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=Ventris\n"
        "Comment=Explains G-code line by line\nExec=Ventris %f\nIcon=ventris\n"
        "Terminal=false\nCategories=Development;\nMimeType=text/x-gcode;\n")
    tool = DIST / "appimagetool.AppImage"
    if not tool.exists():
        url = APPIMAGETOOL_URL.format(arch=platform.machine())
        print("downloading", url)
        urllib.request.urlretrieve(url, tool)
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC)
    out = RELEASE / f"{APP_NAME}-{__version__}-linux-{platform.machine()}.AppImage"
    env = dict(os.environ, ARCH=platform.machine(), APPIMAGE_EXTRACT_AND_RUN="1")
    run([tool, "--no-appstream", appdir, out], env=env)
    return [out]


def make_windows_icon() -> None:
    from PIL import Image
    Image.open(ICON_PNG).save(DIST / "ventris.ico",
                              sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="start the built app once")
    args = parser.parse_args()
    RELEASE.mkdir(parents=True, exist_ok=True)
    DIST.mkdir(exist_ok=True)

    built = pyinstaller()
    if sys.platform == "win32":
        exe = built / f"{APP_NAME}.exe"
    elif sys.platform == "darwin":
        exe = built / "Contents" / "MacOS" / APP_NAME
    else:
        exe = built / APP_NAME
    if args.smoke:
        smoke_test(exe)

    if sys.platform == "win32":
        make_windows_icon()
        outputs = package_windows(built)
    elif sys.platform == "darwin":
        outputs = package_macos(built)
    else:
        outputs = package_linux(built)
        if args.smoke:
            smoke_test(outputs[0])
    for path in outputs:
        print(f"built {path} ({path.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
