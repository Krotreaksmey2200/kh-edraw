"""main.py - Điểm khởi động ứng dụng."""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from core.auth import (
    get_user_info,
    is_logged_in,
    login_with_google,
    logout,
    refresh_credentials,
)
from core.app_icon import app_icon_path, load_app_icon
from core.i18n import t
from core.plus import (
    FirebasePlanError,
    fetch_user_plan_required,
    get_last_error,
)
from core.windows_taskbar import (
    configure_window_taskbar,
    ensure_window_maximized_style,
    set_process_app_user_model_id,
)
from main_window import MainWindow
from ui.splash import SplashScreen


def _ensure_logged_in(splash: SplashScreen | None = None) -> tuple[dict, str] | None:
    """Bắt buộc đăng nhập trước khi vào ứng dụng.

    Trả về (user_info, google_id_token) khi thành công, None nếu người dùng
    huỷ/thoát. google_id_token được dùng tiếp để đổi sang Firebase id_token.

    Khi cần đăng nhập, mở thẳng luồng web login và ẩn splash trong suốt lúc
    người dùng thao tác trên trình duyệt để splash không che cửa sổ đăng nhập.
    """

    def _hide_splash() -> None:
        if splash is not None:
            splash.hide()
            QApplication.processEvents()

    def _show_splash(text: str | None = None) -> None:
        if splash is not None:
            splash.show()
            if text is not None:
                splash.show_message(text)
            QApplication.processEvents()

    if is_logged_in():
        if splash is not None:
            splash.show_message(t("Đang khôi phục phiên đăng nhập…"))
        id_token, _creds = refresh_credentials()
        if id_token:
            return get_user_info(id_token), id_token
        logout()
        _hide_splash()

    while True:
        _hide_splash()
        try:
            id_token, _creds = login_with_google()
            if id_token and is_logged_in():
                if splash is not None:
                    _show_splash()
                    splash.show_message(t("Đăng nhập thành công."))
                return get_user_info(id_token), id_token
            _hide_splash()
            QMessageBox.warning(
                None,
                t("Đăng nhập chưa hoàn tất"),
                t("Không nhận được thông tin xác thực hợp lệ. Vui lòng thử lại."),
            )
        except Exception as e:
            _hide_splash()
            retry = QMessageBox.critical(
                None,
                t("Lỗi đăng nhập"),
                t("Không thể đăng nhập Google:\n{error}\n\nThử lại?", error=e),
                QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Retry,
            )
            if retry != QMessageBox.StandardButton.Retry:
                return None


def main() -> None:
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass
    try:
        set_process_app_user_model_id()
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName("eDraw")
    app.setOrganizationName("HMaths")
    app_icon = load_app_icon()
    if not app_icon.isNull():
        app.setWindowIcon(app_icon)

    if sys.platform.startswith("linux"):
        try:
            from core.linux_desktop import DESKTOP_ID, ensure_desktop_entry

            app.setDesktopFileName(DESKTOP_ID)
            ensure_desktop_entry()
        except Exception:
            pass

    splash = SplashScreen(app_icon)
    splash.show()
    splash.show_message(t("កំពុងចាប់ផ្តើម…"))
    QApplication.processEvents()

    email = "teacher@kh-edraw.org"
    picture = ""
    fb_uid = "kh-edraw-pro"

    splash.show_message(t("កំពុងរៀបចំផ្ទាំងកម្មវិធី…"))
    QApplication.processEvents()
    try:
        window = MainWindow(
            user_plan="PRO",
            user_email=email,
            user_uid=fb_uid,
            user_picture_url=picture,
        )
        app.setWindowIcon(window.windowIcon())
        screen = app.primaryScreen()
        if screen is not None:
            window.setGeometry(screen.availableGeometry())
        window.setWindowState(Qt.WindowState.WindowMaximized)
        hwnd = int(window.winId())
        ensure_window_maximized_style(hwnd)
        configure_window_taskbar(hwnd, icon_path=app_icon_path())
        splash.hide()
        window.showMaximized()
        splash.finish(window)
        QTimer.singleShot(250, window.canvas._prewarm_markdown_renderer)
        sys.exit(app.exec())
    except BaseException:
        splash.finish()
        raise


if __name__ == "__main__":
    main()
