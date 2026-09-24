# 🎨 eDraw - ក្តារខៀនឌីជីថលឆ្លាតវៃ (Smart Digital Whiteboard)

កម្មវិធីក្តារខៀនឌីជីថលកម្រិតខ្ពស់សម្រាប់បង្រៀន និងគូសប្លង់ ជាមួយមុខងារ AI ឆ្លាតវៃ (Google Gemini) បម្លែងអក្សរសរសេរដៃ បង្កើតរូបវិទ្យា/គណិតវិទ្យា TikZ និងគណនាសមីការ LaTeX ដោយស្វ័យប្រវត្តិ។

---

## 🚀 របៀបបើកដំណើរការ (Quick Start)

### ជម្រើសទី ១៖ ប្រើប្រាស់ Script ផ្លូវកាត់
បើក Terminal ក្នុងថត `eDraw_project` រួចវាយ៖
```bash
./run.sh
```

### ជម្រើសទី ២៖ ដំណើរការតាម Python Virtual Environment
```bash
./venv/bin/python main.py
```

### ពិនិត្យសុខភាពប្រព័ន្ធ និង API (Diagnostics)
```bash
./venv/bin/python scripts/test_env.py
```

---

## 🗺️ ផែនទីកូដ — ចង់កែត្រង់ណា ត្រូវចូលទៅកន្លែងណា? (Codebase Map)

| ចំណុចដែលចង់កែប្រែ | ឯកសារដែលត្រូវចូលទៅកែ (File Path) | ការពិពណ៌នា |
| :--- | :--- | :--- |
| **🎨 របារឧបករណ៍ (Toolbar)** | [`ui/toolbar_mixin.py`](ui/toolbar_mixin.py) | កែទំហំប៊ូតុង ពណ៌ background គម្លាត spacing និងការរៀបចំក្រុមប៊ូតុង |
| **🖼️ រូបតំណាងប៊ូតុង (Icons)** | [`ui/icons_mixin.py`](ui/icons_mixin.py) | កែប្រែរូបរាង Icon ប៊ិច ជ័រលុប បន្ទាត់ រាងធរណីមាត្រ និង AI |
| **📐 ក្រដាស់ & ក្រឡាក្តារខៀន (Grid Canvas)** | [`widgets/canvas.py`](widgets/canvas.py) | កែបន្ទាត់ក្រឡា (`_draw_grid`) ទំហំក្រឡា (35px) ពណ៌ផ្ទៃក្តារ និង Mouse Events |
| **🇰🇭 អក្សរខ្មែរ & ការបកប្រែ (i18n)** | [`core/i18n.py`](core/i18n.py) | បន្ថែម ឬកែពាក្យបកប្រែជាភាសាខ្មែរ វៀតណាម និងអង់គ្លេស |
| **🤖 មុខងារ AI សំណួរ (LaTeX Questions)** | [`core/ai_question.py`](core/ai_question.py) | កែ Prompts បង្កើតសំណួរ និងប្រព័ន្ធ Render LaTeX |
| **📐 មុខងារ AI គំនូរធរណីមាត្រ (TikZ AI)** | [`core/tikz_ai.py`](core/tikz_ai.py) | កែ Prompts ស្រង់ទិន្នន័យ TikZ ពីគំនូរ និងការ Compile TikZ |
| **✍️ មុខងារ AI អានអក្សរដៃ (Handwriting AI)** | [`core/handwriting_ai.py`](core/handwriting_ai.py) | កែ OCR Prompt និងការ parse រូបមន្តគណិតវិទ្យា/MathJax |
| **⚙️ ការកំណត់ Gemini & Fallback** | [`core/gemini_models.py`](core/gemini_models.py) | បញ្ជីម៉ូដែល Gemini និងប្រព័ន្ធប្តូរម៉ូដែលជំនួសពេល 503/429 |
| **💾 ការរក្សាទុកការកំណត់ (Settings)** | [`core/app_settings.py`](core/app_settings.py) | រក្សាទុកពណ៌លំនាំដើម ទំហំប៊ិច ភាសា និង API Key ក្នុង QSettings |
| **🪟 ផ្ទាំងកំណត់ & Dialogs ផ្សេងៗ** | [`dialogs/`](dialogs/) | រួមមានផ្ទាំងបញ្ចូល API Key, ផ្ទាំង TikZ, ផ្ទាំងជ្រើសរើស Font |
| **⚡ ដំណើរការសកម្មភាព (Actions & Events)** | [`actions/`](actions/) | គ្រប់គ្រងព្រឹត្តិការណ៍ចុចប៊ូតុង (`ai_mixin.py`, `files_mixin.py`, `modes_mixin.py`) |
| **🏛️ បង្អួចមេ (MainWindow)** | [`main_window.py`](main_window.py) | ផ្គុំរាល់ mixins ទាំងអស់ចូលគ្នា និងគ្រប់គ្រង Hotkeys/Shortcuts |

---

## 🛠️ ការណែនាំអំពីរបៀបកែសម្រួលលម្អិត (Developer How-To Guide)

### ១. របៀបកែពណ៌ ឬទំហំក្រឡាក្រដាស់ (Grid Paper)
បើកឯកសារ [`widgets/canvas.py`](widgets/canvas.py) រួចស្វែងរកមុខងារ `_draw_grid(self, p)`៖
- **ទំហំក្រឡា**៖ ប្តូរតម្លៃ `spacing = 35.0` (ដាក់តូចជាងនេះ ឬធំជាងនេះតាមចិត្ត)
- **ពណ៌បន្ទាត់ក្រឡា**៖ ប្តូរតម្លៃ `grid_color = QColor("#b8cce4")`
- **កម្រាស់បន្ទាត់ក្រឡា**៖ ប្តូរតម្លៃ `pen.setWidthF(0.8)`

### ២. របៀបកែសម្រួល Toolbar (របារឧបករណ៍ខាងលើ)
បើកឯកសារ [`ui/toolbar_mixin.py`](ui/toolbar_mixin.py)៖
- **កម្ពស់ Toolbar**៖ ស្វែងរក `self.main_toolbar.setFixedHeight(44)`
- **ស្ទីលកាត និងប៊ូតុង**៖ ស្វែងរក `_CARD_STYLE` និង `_CARD_BTN_STYLE` សម្រាប់កំណត់ពណ៌ Background, Border, Hover, និង Radius
- **ប្តូរលំដាប់ប៊ូតុង**៖ ស្វែងរកក្នុងអនុគមន៍ `_build_toolbar(self)`

### ៣. របៀបកែសម្រួលពាក្យ ឬការបកប្រែភាសាខ្មែរ
បើកឯកសារ [`core/i18n.py`](core/i18n.py)៖
- ស្វែងរកវចនានុក្រម `_TRANSLATIONS['km']`
- បញ្ចូលពាក្យខ្មែរដែលលោកអ្នកចង់កែ៖
```python
"ពាក្យដើមជាភាសាវៀតណាម": "ពាក្យខ្មែរដែលចង់បង្ហាញ",
```

### ៤. របៀបគ្រប់គ្រងម៉ូដែល AI Gemini & API Key
- API Key ត្រូវបានរក្សាទុកក្នុងប្រព័ន្ធសុវត្ថិភាព `QSettings` (មិនបាត់បង់ពេលបិទកម្មវិធី)។
- បញ្ជីម៉ូដែល fallback ស្ថិតក្នុង [`core/gemini_models.py`](core/gemini_models.py)៖
```python
FALLBACK_GEMINI_MODELS = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-flash-latest",
)
```
នៅពេលម៉ូដែលចម្បងជួបបញ្ហា Server Busy (503) ឬ Quota Limit (429) កម្មវិធីនឹងប្តូរទៅម៉ូដែលបន្ទាប់ដោយស្វ័យប្រវត្ត។

---

## 📦 រចនាសម្ព័ន្ធ Directory ទាំងមូល

```text
eDraw_project/
├── main.py                 # ចំណុចចាប់ផ្តើមនៃកម្មវិធី (Application Entry Point)
├── main_window.py          # បង្អួចធំនៃកម្មវិធី (Main Window Integration)
├── run.sh                  # Script ចុចបើកកម្មវិធីភ្លាមៗ (One-click Launcher)
├── requirements.txt        # បញ្ជីបណ្ណាល័យ Python Dependencies
├── .gitignore              # បញ្ជីសម្រាំងមិន Push ឯកសារបណ្តោះអាសន្ន
│
├── ui/                     # ការរៀបចំចំណុចប្រទាក់អ្នកប្រើ (User Interface & Mixins)
│   ├── toolbar_mixin.py    # រចនាប័ទ្មរបារឧបករណ៍ខាងលើ (Toolbar Layout & Styles)
│   ├── icons_mixin.py      # រូបតំណាងប៊ូតុង (Vector Icons Generator)
│   └── splash.py           # ផ្ទាំងបើកដំបូង (Splash Screen)
│
├── widgets/                # សមាសភាគក្រាហ្វិក (Custom Qt Widgets)
│   ├── canvas.py           # ផ្ទៃក្តារខៀន ក្រឡា ប៊ិច និងបន្ទាត់គំនូរ
│   └── mirror_window.py    # ផ្ទាំងបញ្ចាំង Slide ទីពីរ
│
├── core/                   # ម៉ាស៊ីនដំណើរការស្នូល (Core Engines & Business Logic)
│   ├── gemini_models.py    # ប្រព័ន្ធតភ្ជាប់ Gemini API & Auto-Fallback
│   ├── ai_question.py      # AI បង្កើតសំណួរ និងលំហាត់
│   ├── tikz_ai.py          # AI បង្កើតកូដរូបគណិតវិទ្យា TikZ
│   ├── handwriting_ai.py   # AI អានអក្សរសរសេរដៃ (OCR Engine)
│   ├── latex_engine.py     # ម៉ាស៊ីន Compile រូបមន្ត LaTeX / pdflatex
│   ├── app_settings.py     # រក្សាទុក និងទាញយកការកំណត់ (Persistent Settings)
│   └── i18n.py             # វចនានុក្រមពហុភាសា (Khmer, Vietnamese, English)
│
├── dialogs/                # ផ្ទាំងបង្អួចកំណត់នានា (Popup Dialogs & Modals)
│   ├── ai_question_dialog.py
│   ├── tikz_ai_dialog.py
│   ├── handwriting_settings_dialog.py
│   └── gemini_settings_dialog.py
│
├── actions/                # សកម្មភាពចុច និង Logic មុខងារ
│   ├── ai_mixin.py
│   ├── files_mixin.py
│   └── modes_mixin.py
│
└── scripts/                # ឧបករណ៍ជំនួយការអភិវឌ្ឍន៍ (Dev & Diagnostic Tools)
    └── test_env.py         # ឧបករណ៍ត្រួតពិនិត្យសុខភាពប្រព័ន្ធ និង API
```

---

## 💡 គន្លឹះបន្ថែមសម្រាប់ Developer
- **LaTeX Support**៖ ដើម្បីឱ្យរូបមន្តគណិតវិទ្យាបង្ហាញច្បាស់ស្អាត ១០០% សូមប្រាកដថាប្រព័ន្ធមានតម្លើង MacTeX ឬ TeXLive (`which pdflatex`)។
- **Debug Logs**៖ អាចតាមដាន log បានដោយដំណើរការកម្មវិធីតាម Terminal នោះរាល់ការហៅ API និងសកម្មភាពនឹងបង្ហាញលើ Console ភ្លាមៗ។
