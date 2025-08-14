# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

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
