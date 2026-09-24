#!/usr/bin/env python3
"""Build script for khedraw.app and khedraw.dmg on macOS."""

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
DMG_OUTPUT = ROOT_DIR / "khedraw.dmg"
DMG_STAGING = ROOT_DIR / "dmg_staging"

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
    
    print("\n=== Step 2: Creating Drag-and-Drop DMG (khedraw.dmg) ===")
    os.chdir(ROOT_DIR)
    
    if DMG_STAGING.exists():
        subprocess.run(["chmod", "-R", "u+w", str(DMG_STAGING)], check=False)
        shutil.rmtree(DMG_STAGING, ignore_errors=True)
        
    DMG_STAGING.mkdir(parents=True, exist_ok=True)
    
    # Copy .app to staging
    print("Copying khedraw.app into DMG staging area...")
    shutil.copytree(APP_PATH, DMG_STAGING / "khedraw.app")
    
    # Create Applications symlink for drag and drop
    apps_symlink = DMG_STAGING / "Applications"
    if apps_symlink.is_symlink() or apps_symlink.exists():
        apps_symlink.unlink()
    os.symlink("/Applications", str(apps_symlink))
    
    if DMG_OUTPUT.exists():
        DMG_OUTPUT.unlink()
        
    # Build DMG using hdiutil
    cmd = [
        "hdiutil", "create",
        "-volname", "khedraw",
        "-srcfolder", str(DMG_STAGING),
        "-ov",
        "-format", "UDZO",
        str(DMG_OUTPUT)
    ]
    
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    
    # Clean staging
    shutil.rmtree(DMG_STAGING, ignore_errors=True)
    
    if DMG_OUTPUT.exists():
        size_mb = DMG_OUTPUT.stat().st_size / (1024 * 1024)
        print(f"\n✅ Successfully generated: {DMG_OUTPUT} ({size_mb:.2f} MB)")
    else:
        print("\n❌ Failed to create khedraw.dmg")
        sys.exit(1)

    print("\n=== Step 3: Installing directly to /Applications ===")
    app_install_dest = Path("/Applications/khedraw.app")
    subprocess.run(["rm", "-rf", str(app_install_dest)], check=False)
    subprocess.run(["cp", "-R", str(APP_PATH), "/Applications/khedraw.app"], check=True)
    subprocess.run(["touch", str(app_install_dest)], check=False)
    subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister", "-f", str(app_install_dest)], check=False)
    print(f"✅ Installed and updated in /Applications/khedraw.app!")

if __name__ == "__main__":
    main()
