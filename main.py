"""
main.py - MedTracker entry point.

    python main.py          use your real database
    python main.py --demo   use a separate demo database filled with sample data
"""

import argparse
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

# Make matplotlib use Qt (PySide6) - must happen before matplotlib is imported anywhere.
os.environ.setdefault("QT_API", "pyside6")
import matplotlib  # noqa: E402

matplotlib.use("QtAgg")

from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402

log = logging.getLogger("medtracker")


def parse_args(argv):
    parser = argparse.ArgumentParser(prog=config.APP_NAME, description=config.APP_DESCRIPTION)
    parser.add_argument("--demo", action="store_true",
                        help="use a separate demo database filled with sample data")
    # parse_known_args ignores extra arguments some systems pass (e.g. macOS -psn_...)
    args, _unknown = parser.parse_known_args(argv)
    return args


def setup_logging() -> None:
    handler = RotatingFileHandler(config.log_path(), maxBytes=1_000_000, backupCount=3,
                                  encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.WARNING)      # other libraries: warnings and errors only
    root.addHandler(handler)
    log.setLevel(logging.INFO)          # MedTracker's own messages


def install_exception_handler() -> None:
    """
    Any unexpected error is written to the log file and shown in a friendly
    message box, so the packaged app never silently crashes.
    """
    def handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        log.critical("Unexpected error", exc_info=(exc_type, exc_value, exc_tb))
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None, "Unexpected error",
                f"Sorry, something went wrong:\n\n{exc_type.__name__}: {exc_value}\n\n"
                f"Your saved data is safe. Full details were written to:\n{config.log_path()}\n\n"
                f"If this keeps happening, please send that file to your support person.")
        else:  # error before the window exists
            sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle


def set_windows_app_id() -> None:
    """Make Windows show MedTracker's own icon in the taskbar (not Python's)."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"MedTracker.MedTracker.{config.APP_VERSION}")
        except Exception:  # not critical
            pass


def main(argv=None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    setup_logging()
    install_exception_handler()
    set_windows_app_id()

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    app.setApplicationVersion(config.APP_VERSION)
    from ui.theme import apply_theme
    apply_theme(app)  # same modern look on Windows, macOS and Linux
    icon_file = config.resource_path("resources/icon.png")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    path = config.db_path(demo=args.demo)
    log.info("Starting %s %s (demo=%s) with database %s",
             config.APP_NAME, config.APP_VERSION, args.demo, path)
    try:
        conn = db.connect(path)
    except Exception as exc:
        log.exception("Could not open database")
        QMessageBox.critical(None, "Cannot open database",
                             f"The database could not be opened:\n{path}\n\n{exc}")
        return 1

    if args.demo:
        import demo_data
        demo_data.seed_demo(conn)

    from ui.main_window import MainWindow  # imported late so errors above show nicely
    window = MainWindow(conn, path, demo=args.demo)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
