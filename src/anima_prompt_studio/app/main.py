from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from anima_prompt_studio.repositories import default_data_dir


def configure_logging() -> None:
    log_dir = default_data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler], format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main() -> int:
    configure_logging()
    try:
        from PySide6.QtWidgets import QApplication, QMessageBox
        from anima_prompt_studio.ui.main_window import MainWindow
    except ImportError as exc:
        print("无法启动桌面界面：请先运行 pip install -e . 安装 PySide6。", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 2
    app = QApplication(sys.argv)
    app.setApplicationName("ANIMA Prompt Studio")
    app.setOrganizationName("AnimaPromptStudio")
    app.setStyle("Fusion")
    try:
        window = MainWindow(); window.show(); return app.exec()
    except Exception as exc:
        logging.exception("应用启动失败")
        QMessageBox.critical(None, "启动失败", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

