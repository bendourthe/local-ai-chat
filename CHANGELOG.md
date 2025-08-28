# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.2.0] - 2025-08-28

### Added
- **Typing Indicator System**: Real-time typing animations with debounced 300ms delay and chat-specific waiting states
- **Advanced Model Management**: Model size hints, progress dialogs for downloads/deletions, and threaded operations for responsive UI
- **Smart Chat Storage**: Home directory storage with structured `YYYY-MM-DD_title.json` naming and collision handling
- **Device Backend Detection**: GPU detection via nvidia-smi and PowerShell integration with backend display in chat interface
- **Context Management System**: Token usage tracking, configurable warnings, progress bar visualization, and per-message token counts
- **Enhanced Settings**: Chat display preferences for role/timestamp visibility with live updates and persistence
- **Token Tracking Integration**: Real-time monitoring of input, output, and reasoning tokens during AI inference via TokenTracker class
- **Markdown Support**: Rich text rendering in chat messages for improved formatting
- **Dynamic UI Elements**: Bubble width calculations, smooth scrolling animations, and deferred scroll handling
- **New Core Module**: `src/core/tokens.py` for token estimation utilities

### Enhanced
- Chat interface with improved message handling and scroll behavior
- Settings dialog refactored from `settings_dialog.py` to `settings.py` for consistency
- Error handling and robustness across chat operations and file management
- Message persistence with automatic timestamp updates and filename adjustments
- Model selection UI to show download status and provide better user feedback

### Fixed
- Chat creation logic to ensure current chat exists before sending messages
- Token synchronization between chat bubbles and tracking system
- Chat cleanup and typing indicator management during chat transitions
- File path generation with proper error handling and unique naming

### Changed
- Chat storage location moved from LocalAppData to user home directory with structured organization
- Settings dialog structure and signal handling for immediate UI updates
- Token estimation to use more accurate tiktoken-compatible algorithms

## [0.1.0] - 2025-08-14

### Added
- Modernized Settings dialog UI:
  - Larger, seamless tabs (document mode + QSS for QTabWidget/QTabBar)
  - Thin, rounded vertical scrollbar with transparent track for settings content
  - Right-aligned color pickers with improved label visibility (wrap + min width)
- Theme system with centralized QSS generation and theme persistence (`src/gui/styles.py`, `src/gui/theme.json`).
- DEVLOG.md with task list, development history, and troubleshooting.
- pyproject.toml with basic project metadata.

### Fixed
- Model selector now populates correctly on startup by calling `_refresh_models()` in `gui.app.MainWindow`.
- Safer separator handling and placeholder text when no models are available.

### Changed
- README updated to reflect PySide6 GUI, current entry point, and improved instructions.

## [Unreleased]
- Add unit tests for theme save/restore and CLI parsing.
- CI for linting and packaging.
- Optional: binary distribution improvements via build.ps1.
