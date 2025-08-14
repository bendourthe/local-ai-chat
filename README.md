# Foundry Local Desktop Chat (Windows)

Version: 0.1.0

A simple Windows desktop app (PySide6/Qt) to manage Microsoft Foundry Local:
- Install Foundry Local via winget
- List available models
- Select a model and chat with clean, readable streaming
- Persist chats in a sidebar (load, rename, delete)

## What's new in 0.1.0
- Modernized Settings dialog: larger borderless tabs, minimal scrollbar, right-aligned color pickers, anti-cropping labels.
- Model selector now populates on startup; improved separator and empty-state handling.
- Centralized theme styling and persistence via QSS and `src/gui/theme.json`.
- Added DEVLOG.md, CHANGELOG.md, and pyproject.toml.

## Prerequisites
- Windows 10/11
- Python 3.9+ (recommended 3.10+)
- PowerShell

## Quick Start (Run from source)
```powershell
# From the project root
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python .\src\main.py
```

## Build a Windows .exe
```powershell
# From the project root
.\build.ps1
# Output: .\dist\FoundryLocalChat.exe
```

## Features
- Clean UI built with PySide6 (Qt)
- One-click "Install Foundry" (runs `winget install Microsoft.FoundryLocal`)
- Model discovery via `foundry model list`
- Interactive chat runs `foundry model run <model>` under the hood
- Chat sidebar with persistence
  - Windows: `%LOCALAPPDATA%/FoundryLocalChat/data/chats/*.json`
  - Linux/macOS: `~/.local/share/FoundryLocalChat/data/chats/*.json`
- Delete chats on demand

## Notes
- Installing Foundry Local may require elevation (UAC). If installation fails, run the app as Administrator, or run the command in an elevated PowerShell:
  ```powershell
  winget install Microsoft.FoundryLocal
  ```
- First-time model run will download model weights. This may take time and disk space.
- Output of the CLI is parsed to show assistant replies. Raw logs are captured internally to improve display, but the assistant stream shown in the UI focuses on the final assistant messages.

## Folder Structure
```
local-ai-chat/
  README.md
  CHANGELOG.md
  DEVLOG.md
  pyproject.toml
  requirements.txt
  build.ps1
  .gitignore
  src/
    main.py
    gui/
      app.py
      settings_dialog.py
      styles.py
    core/
      foundry_cli.py
      storage.py
  (Chat data is stored under LocalAppData, not in this repo)
```

## Troubleshooting
- If `foundry` is not recognized: click "Install Foundry" in the app or run the winget command above.
- If model list is empty: ensure `foundry model list` works in PowerShell. You may need to restart PowerShell after installation.
- If chat does not start: verify the selected model exists and test it manually in a terminal: `foundry model run <model>`.

## License
MIT
