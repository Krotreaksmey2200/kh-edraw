#!/usr/bin/env python3
"""
scripts/test_env.py
ឧបករណ៍ពិនិត្យសុខភាពប្រព័ន្ធ និងការកំណត់ (eDraw Environment & Diagnostics Tool)
"""
import sys
import shutil
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

def check_system():
    print("=" * 60)
    print(" 🛠️  eDraw System Diagnostics / ការពិនិត្យប្រព័ន្ធ eDraw")
    print("=" * 60)

    # 1. Python version
    print(f"\n1. Python Version: {sys.version.split()[0]} (Path: {sys.executable})")

    # 2. PyQt6
    try:
        from PyQt6.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        print(f"2. PyQt6: OK (PyQt {PYQT_VERSION_STR}, Qt {QT_VERSION_STR})")
    except Exception as e:
        print(f"2. PyQt6: FAILED ({e})")

    # 3. LaTeX Engine (pdflatex)
    pdflatex_path = shutil.which("pdflatex") or "/Library/TeX/texbin/pdflatex"
    if Path(pdflatex_path).is_file():
        print(f"3. pdflatex: OK ({pdflatex_path})")
    else:
        print("3. pdflatex: Not found in PATH (LaTeX formulas will use fallback)")

    # 4. Settings & Gemini API
    from core.app_settings import load_gemini_api_key, load_gemini_model, load_language
    api_key = load_gemini_api_key().strip()
    model = load_gemini_model()
    lang = load_language()

    print(f"4. ភាសា (Language): {lang}")
    print(f"5. Gemini Model: {model}")
    if api_key:
        masked_key = api_key[:6] + "..." + api_key[-4:]
        print(f"6. Gemini API Key: {masked_key} (រួចរាល់ / Ready)")
    else:
        print("6. Gemini API Key: មិនទាន់កំណត់ (Not set)")

    # 5. Quick Ping to Gemini
    if api_key:
        print("\nកំពុងសាកល្បងហៅ Gemini API (Testing Gemini Connection)...")
        try:
            from core.gemini_models import call_gemini_generate_with_fallback
            text, used_model = call_gemini_generate_with_fallback(
                api_key=api_key,
                model=model,
                contents="Ping",
                timeout_ms=10000,
            )
            print(f"   ✓ ជោគជ័យ (Success)! ឆ្លើយតបពី: {used_model}")
        except Exception as e:
            print(f"   ✗ កំហុស (Failed): {e}")

    print("\n" + "=" * 60)
    print("ការពិនិត្យបានបញ្ចប់! (Diagnostics Completed)")
    print("=" * 60)

if __name__ == "__main__":
    check_system()
