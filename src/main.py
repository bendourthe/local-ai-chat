"""
Application entry point for Foundry Local Desktop Chat.

Starts the Qt UI.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
# Standard library imports
import sys

# Third-party libraries
from PySide6.QtWidgets import QApplication

# Local application imports
from gui.app import MainWindow

def run_app() -> None:
    """Start the Qt application and show the main window."""
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    run_app()
