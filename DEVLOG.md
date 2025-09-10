# Task List

## Completed in v0.2.1
- [x] Implement ContextManager class for intelligent conversation context handling
- [x] Add GPUMonitor class for real-time memory usage tracking and cleanup
- [x] Enhance FoundryCLI with session tracking and memory management
- [x] Update storage settings for GPU memory thresholds and context windows
- [x] Create comprehensive test framework for context retention and GPU memory
- [x] Fix test suite execution issues (Context Retention and Response Performance 0/0 → 7/7)
- [x] Add TestResultAggregator proper constructor calls and result collection
- [x] Implement emergency cleanup system with process management and signal handlers
- [x] Add timeout decorators and proper cleanup mechanisms for test reliability
- [x] Fix format_console_output parameter order and missing configuration keys

## Completed in v0.2.0
- [x] Fix model selector dropdown population on startup
- [x] Modernize Settings dialog (tabs, scrollbar, color pickers alignment) 
- [x] Prevent label cropping in Settings color rows
- [x] Update documentation (README) with version and what's new
- [x] Add project metadata (CHANGELOG.md, pyproject.toml)
- [x] Implement typing indicator functionality
- [x] Add model management features with progress dialogs
- [x] Enhance chat storage with home directory structure
- [x] Add device backend detection (GPU via nvidia-smi)
- [x] Implement context management and token tracking
- [x] Add chat settings management (role/timestamp visibility)
- [x] Refactor settings dialog structure
- [x] Integrate real-time token tracking system

## Future Tasks
- [ ] Add unit tests for theme save/restore and CLI parsing
- [ ] Add CI to lint and verify packaging metadata
- [ ] Optional: Provide binary artifacts via build.ps1 improvements

# Development History

## Application architecture and design decisions
- The app is a desktop GUI built with PySide6. Entry point: `src/main.py` starting `gui.app.MainWindow`.
- CLI integration encapsulated in `src/core/foundry_cli.py`; storage operations in `src/core/storage.py`.
- Token management handled by `src/core/tokens.py` with real-time tracking integration.
- Theming centralizes QSS generation in `src/gui/styles.py` with a minimal schema persisted to `src/gui/theme.json`.
- Settings dialog (`src/gui/settings.py`) builds a Theme tab from theme keys grouped by sections, enabling live preview and save/restore.
- Chat storage moved to user home directory with structured naming based on creation date and title.

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

## v0.2.1 Major Features Added

### Context Management System
- New ContextManager class for intelligent conversation context handling within token limits
- Truncation and summarization strategies for optimal memory usage
- Token limit enforcement with configurable thresholds
- Integration with chat sessions for persistent context tracking

### GPU Memory Monitoring
- GPUMonitor class for real-time memory usage tracking
- Automatic cleanup triggers when thresholds are exceeded  
- Memory baseline tracking and delta calculations
- Integration with FoundryCLI for session-aware memory management

### Enhanced Session Tracking
- FoundryCLI improvements with chat session management attributes
- Memory baseline tracking (`_memory_baseline`) and process cleanup locks
- Context caching (`_context_cache`) for efficient memory usage
- Session isolation and proper cleanup mechanisms

### Comprehensive Test Framework
- Full test suites for context retention, GPU memory usage, and response performance
- Timeout handling with 120-second limits and proper cleanup
- Test result aggregation with accurate reporting (fixed 0/0 → 7/7 test counts)
- Emergency cleanup system with process management and signal handlers

### Technical Infrastructure
- Non-blocking I/O handlers to prevent hanging during model operations
- Thread-safe unload_model() with comprehensive GPU memory cleanup
- Enhanced send_prompt() with intelligent context building
- Proper test runner functions for result collection and aggregation

## v0.2.0 Major Features Added

### Typing Indicator System
- Debounced typing indicators with 300ms delay for better UX
- Chat-specific waiting states and proper cleanup on chat transitions
- Smooth animations with deferred scrolling logic

### Advanced Model Management
- Model size hints retrieval before download
- Progress dialogs with streaming output for model operations
- Threading for non-blocking UI during downloads/deletions
- Enhanced model selection UI with download status

### Token Tracking and Context Management
- Real-time token usage monitoring (input, output, reasoning)
- Context usage warnings with configurable thresholds
- Per-message token counts displayed in chat bubbles
- Progress bar visualization of context usage
- Integration with TokenTracker class for accurate metrics

### Chat Interface Enhancements
- Markdown rendering support for rich text formatting
- Dynamic bubble width calculations
- GPU detection and backend display
- Role and timestamp visibility toggles
- Improved scrolling and message handling

### Storage Improvements
- Chat files stored in user home directory
- Structured naming: `YYYY-MM-DD_title.json`
- Automatic file management and error handling
- Unique path generation with collision handling

## Additional context
- External chat scrollbar previously implemented and styled to match theme.
- Theme system supports nested or flat JSON with backward-compatible key aliases.
- Token estimation uses tiktoken-compatible algorithms for accuracy.
- GPU detection supports CUDA backends via nvidia-smi integration.

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

## Token tracking integration challenges
- Synchronization between chat bubble counts and tracker metrics
- Ensuring accurate token display across chat switches
- Managing token state during chat creation/deletion
- Real-time updates without performance impact

## Chat storage migration to home directory
- Moved from LocalAppData to structured home directory storage
- Implemented collision-safe naming with date prefixes
- Added robust error handling for file operations
- Maintained backward compatibility during transition
