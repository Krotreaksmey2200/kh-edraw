#!/usr/bin/env python3
"""Build script for khedraw.app and khedraw.pkg on macOS."""

import os
import sys
import shutil
import subprocess
from pathlib import Path
import dis

# Work around Python 3.10.0 dis.py bug (bpo-45738)
orig_get_const_info = dis._get_const_info

def safe_get_const_info(const_index, const_list):
    argval = const_index
    if const_list is not None:
        if 0 <= const_index < len(const_list):
            argval = const_list[const_index]
        else:
            argval = f"<const {const_index}>"
    return argval, repr(argval)

dis._get_const_info = safe_get_const_info

import PyInstaller.__main__
import PyInstaller.building.utils as pyi_utils

def safe_pyi_rmtree(path):
    if not os.path.exists(path):
        return
    try:
        subprocess.run(["chmod", "-R", "777", str(path)], check=False)
        for root, dirs, files in os.walk(path):
            for d in dirs:
                try:
                    os.chmod(os.path.join(root, d), 0o777)
                except Exception:
                    pass
            for f in files:
                try:
                    os.chmod(os.path.join(root, f), 0o777)
                except Exception:
                    pass
        os.chmod(path, 0o777)
        subprocess.run(["rm", "-rf", str(path)], check=False)
        if os.path.exists(path):
            shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass

pyi_utils._rmtree = safe_pyi_rmtree

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR / "eDraw_project"
DIST_DIR = ROOT_DIR / "release_dist"
APP_PATH = DIST_DIR / "khedraw.app"
PKG_OUTPUT = ROOT_DIR / "khedraw.pkg"

def main():
    print("=== Step 1: Building khedraw.app with PyInstaller ===")
    
    if DIST_DIR.exists():
        subprocess.run(["chmod", "-R", "u+w", str(DIST_DIR)], check=False)
        shutil.rmtree(DIST_DIR, ignore_errors=True)
            
    os.chdir(PROJECT_DIR)
    
    PyInstaller.__main__.run([
        "--noconfirm",
        "--clean",
        "--distpath", str(DIST_DIR),
        "khedraw.spec",
    ])
    
    if not APP_PATH.exists():
        print(f"Error: {APP_PATH} was not created!")
        sys.exit(1)
        
    print(f"Successfully built: {APP_PATH}")
    
    print("\n=== Step 2: Creating macOS Installer Package (khedraw.pkg) ===")
    os.chdir(ROOT_DIR)
    
    if PKG_OUTPUT.exists():
        PKG_OUTPUT.unlink()
        
    cmd = [
        "pkgbuild",
        "--install-location", "/Applications",
        "--component", str(APP_PATH),
        str(PKG_OUTPUT),
    ]
    
    print("Running:", " ".join(cmd))
    res = subprocess.run(cmd, check=True)
    
    if PKG_OUTPUT.exists():
        size_mb = PKG_OUTPUT.stat().st_size / (1024 * 1024)
        print(f"\n✅ Successfully generated: {PKG_OUTPUT} ({size_mb:.2f} MB)")
    else:
        print("\n❌ Failed to create khedraw.pkg")
        sys.exit(1)

    print("\n=== Step 3: Installing to /Applications (Visible in Launchpad) ===")
    app_install_dest = Path("/Applications/khedraw.app")
    if app_install_dest.exists():
        subprocess.run(["chmod", "-R", "u+w", str(app_install_dest)], check=False)
        shutil.rmtree(app_install_dest, ignore_errors=True)
    shutil.copytree(APP_PATH, app_install_dest)
    subprocess.run(["touch", str(app_install_dest)], check=False)
    # Register with LaunchServices
    subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-f", str(app_install_dest)], check=False)
    print(f"✅ Installed to {app_install_dest} and registered with LaunchServices / Launchpad!")

if __name__ == "__main__":
    main()
