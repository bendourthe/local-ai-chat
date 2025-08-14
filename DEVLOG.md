# Task List

- [x] Fix model selector dropdown population on startup
- [x] Modernize Settings dialog (tabs, scrollbar, color pickers alignment)
- [x] Prevent label cropping in Settings color rows
- [x] Update documentation (README) with version and what's new
- [x] Add project metadata (CHANGELOG.md, pyproject.toml)
- [ ] Add unit tests for theme save/restore and CLI parsing
- [ ] Add CI to lint and verify packaging metadata
- [ ] Optional: Provide binary artifacts via build.ps1 improvements

# Development History

## Application architecture and design decisions
- The app is a desktop GUI built with PySide6. Entry point: `src/main.py` starting `gui.app.MainWindow`.
- CLI integration encapsulated in `src/core/foundry_cli.py`; storage operations in `src/core/storage.py`.
- Theming centralizes QSS generation in `src/gui/styles.py` with a minimal schema persisted to `src/gui/theme.json`.
- Settings dialog (`src/gui/settings_dialog.py`) builds a Theme tab from theme keys grouped by sections, enabling live preview and save/restore.

## UI modernization (Settings dialog)
- Tabs: Enabled document mode and added QSS to remove outlines and enlarge fonts, blending tabs with content.
- Scrollbar: Added targeted QSS for `QScrollArea#SettingsScroll` to render only a thin rounded handle, fully transparent track.
- Color pickers: Added layout stretch to push controls right; labels wrap with a minimum width and row wrap policy to avoid cropping.

## Model dropdown population
- Root cause: `_refresh_models()` not called on startup in `gui.app.MainWindow`.
- Fix: Call `_refresh_models()` during initialization; improve separator logic and empty-state placeholder behavior.

## Technical constraints and trade-offs
- QSS targeting: Used `objectName` (`SettingsScroll`) to scope scrollbar styling to the settings page without affecting chat.
- Label wrapping: Chose `QFormLayout.WrapLongRows` plus measured minimum width and constrained editor width to minimize truncation while maintaining alignment.
- Packaging: Minimal `pyproject.toml` with setuptools for future-ready metadata without restructuring to a fully installable package yet.

## Additional context
- External chat scrollbar previously implemented and styled to match theme.
- Theme system supports nested or flat JSON with backward-compatible key aliases.

# Troubleshooting

## Model dropdown empty on startup
- Verified creation of `QComboBox` in `gui.app.MainWindow.__init__` and population in `_refresh_models()`.
- Traced data sources: CLI via `FoundryCLI.list_models()` and local via `storage.get_downloaded_models()`.
- Confirmed `_refresh_models()` not invoked during init; added the call and validated behavior.
- Improved UX: conditional separator, placeholder when lists are empty.

## Settings dialog label cropping
- Observed truncation with long variable names.
- Implemented: label word-wrap, left alignment, measured minimum width, row wrap policy; constrained hex editor width and right-aligned controls.
- Verified visual alignment and no cropping at typical window sizes.
