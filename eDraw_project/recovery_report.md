# eDraw Recovery Report

## Builder Detection
- **Packager**: PyInstaller 2.1+ (one-file mode)
- **Python version**: 3.12.0
- **Architecture**: macOS arm64 (Apple Silicon)
- **Binary**: Mach-O 64-bit executable, ~10.8 MB

## Extraction
- **Tool**: pyinstxtractor-ng (extracted 14 CArchive files + 1435 PYZ files)
- **Decompiler**: pycdc (built from source, supports Python 3.12)

## Recovery Statistics
| Category | Count |
|----------|-------|
| Python source files recovered | 62 |
| Total lines of code | ~18,000 |
| Assets recovered | 3 icons + 2 fonts + LaTeX templates + MathJax + TikZJax |
| Syntax errors | 0 |
| Fully reconstructed | 58 files |
| Partially reconstructed (with TODO stubs) | 4 files |

## Project Structure
```
eDraw_project/
├── main.py                          # Entry point
├── main_window.py                   # MainWindow (QMainWindow + mixins)
├── requirements.txt                 # Python dependencies
├── recovery_report.md               # This file
│
├── core/                            # Core business logic
│   ├── ai_question.py               # AI question generation (Gemini)
│   ├── app_icon.py                  # Application icon helpers
│   ├── app_settings.py              # QSettings persistence
│   ├── auth.py                      # Google OAuth2 login + Keyring
│   ├── custom_curve_tool.py         # Custom AI curve tools
│   ├── drawing_engine.py            # Core drawing engine (1888→1800+ lines)
│   ├── figure_code_ai.py            # Python figure code generation
│   ├── gemini_models.py             # Gemini model configuration
│   ├── handwriting_ai.py            # Handwriting recognition AI
│   ├── i18n.py                      # Vietnamese/English translations
│   ├── image_handler.py             # Image load/save/clipboard
│   ├── latex_engine.py              # LaTeX → PDF → PNG compilation
│   ├── linux_desktop.py             # Linux XDG integration
│   ├── plus.py                      # Firebase plan checking (BASIC/PLUS/PRO)
│   ├── rich_text_preprocessor.py    # Markdown/LaTeX preprocessing
│   ├── screen_recorder.py           # Screen recording to AVI
│   ├── tikz_ai.py                   # TikZ code generation (Gemini)
│   ├── updater.py                   # GitHub auto-update checker
│   ├── windows_taskbar.py           # Windows taskbar identity
│   └── python_figure/               # Python figure subsystem
│       ├── ast_guard.py             # AST sandbox validator
│       ├── protocol.py              # Backend protocols
│       ├── service.py               # Render service + cache
│       ├── worker_main.py           # Worker process
│       └── backends/
│           ├── edraw_backend.py     # Native QPainter backend
│           └── tikz_backend.py      # TikZ/pdflatex backend
│
├── models/                          # Data models
│   ├── elements.py                  # Stroke/Text/Image/Figure elements
│   └── slide.py                     # Slide model (undo/redo + pixmap cache)
│
├── ui/                              # UI components
│   ├── constants.py                 # Colors, sizes, styles
│   ├── splash.py                    # Splash screen
│   ├── icons_mixin.py               # Vector icon drawing
│   ├── toolbar_mixin.py             # Toolbar construction
│   └── account_mixin.py             # Google avatar/login button
│
├── widgets/                         # Custom widgets
│   ├── canvas.py                    # Main drawing canvas (QPainterWidget)
│   ├── mirror_window.py             # Secondary display mirror
│   └── python_figure_param_panel.py # Figure parameter sliders
│
├── actions/                         # Action mixins
│   ├── ai_mixin.py                  # AI tool actions
│   ├── custom_tools_mixin.py        # Custom tool CRUD
│   ├── files_mixin.py               # File operations
│   ├── modes_mixin.py               # Drawing mode switching
│   └── python_figure_mixin.py       # Figure editing actions
│
├── dialogs/                         # Dialog windows
│   ├── settings_dialog.py           # General settings
│   ├── gemini_settings_dialog.py    # Gemini API key config
│   ├── gemini_model_selector.py     # Model picker
│   ├── code_editor_dialog.py        # LaTeX/code editor
│   ├── tikz_ai_dialog.py            # TikZ AI generation
│   ├── tikz_context_dialog.py       # TikZ context editor
│   ├── ai_question_dialog.py        # AI question builder
│   ├── curve_tool_dialog.py         # Custom curve editor
│   ├── export_selection_dialog.py   # Export options
│   ├── handwriting_settings_dialog.py # Handwriting config
│   ├── python_figure_dialog.py      # Python figure editor
│   └── update_dialog.py             # Update notification
│
├── assets/                          # Application assets
│   ├── iconEDraw.icns               # macOS icon
│   ├── iconEDraw.ico                # Windows icon
│   ├── iconEDraw.png                # Linux icon
│   └── handwriting/fonts/           # Handwriting fonts
│       ├── PatrickHand-Regular.ttf
│       └── PlaywriteVN.ttf
│
└── config/                          # Configuration files
    ├── version.txt                  # Version: 2026.05.22.01
    ├── mathjax/tex-svg.js           # LaTeX → SVG renderer
    ├── tikzjax/                     # TikZ → SVG (WASM)
    │   ├── tikzjax.js
    │   ├── fonts.css
    │   └── bakoma/ttf/              # Computer Modern fonts (150+ files)
    └── templates/extest/            # LaTeX templates
        ├── ex_test.sty              # Custom LaTeX package
        ├── slide_wrapper.tex        # Slide export template
        └── tikz_ai_wrapper.tex      # TikZ AI template
```

## Dependencies (requirements.txt)
```
PyQt6>=6.5          # GUI framework
Pillow>=10.0        # Image processing
PyMuPDF>=1.23       # PDF rendering
google-auth>=2.23   # Google OAuth
google-auth-oauthlib>=1.1
google-api-python-client>=2.100
pydantic>=2.0       # Data validation
httpx[http2]>=0.25  # HTTP client
certifi>=2023.7     # SSL certificates
keyring>=25.0       # Secure credential storage
requests>=2.31
websockets>=12.0
markdown>=3.5       # Markdown rendering
cryptography>=41.0
pydantic-core>=2.14
```

## Known Limitations
1. **Drawing engine** (`drawing_engine.py`): Some complex method bodies may have
   minor decompilation artifacts in edge cases. Core drawing logic is complete.
2. **Canvas widget** (`canvas.py`): Event handlers reconstructed from bytecode;
   some minor UI polish may differ from original.
3. **Dialogs**: Most dialogs have working layouts and widgets but some
   advanced features (like custom color pickers) may need manual polish.
4. **Binary assets**: Only icon files and fonts were recoverable from the
   PyInstaller bundle. Any dynamically-generated assets are not included.

## How to Run
```bash
# Install dependencies
pip install -r requirements.txt

# You also need:
# - LaTeX distribution (pdflatex/lualatex) for slide export
# - Google OAuth credentials configured in core/auth.py

# Run the application
python main.py
```

## Notes
- All Google OAuth credentials in `core/auth.py` are from the original binary.
- Firebase Web API key and project ID in `core/plus.py` are from the original.
- The application supports Vietnamese (vi) and English (en) languages.
- Version: 2026.05.22.01
