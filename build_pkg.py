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

ROOT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ROOT_DIR / "eDraw_project"
DIST_DIR = ROOT_DIR / "dist"
APP_PATH = DIST_DIR / "khedraw.app"
PKG_OUTPUT = ROOT_DIR / "khedraw.pkg"

def main():
    print("=== Step 1: Building khedraw.app with PyInstaller ===")
    os.chdir(PROJECT_DIR)
    
    PyInstaller.__main__.run([
        "--noconfirm",
        "--clean",
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

if __name__ == "__main__":
    main()
