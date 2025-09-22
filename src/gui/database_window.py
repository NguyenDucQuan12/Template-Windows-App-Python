# -*- coding: utf-8 -*-
"""
DatabasePage (lazy-load)
- Trang tổng: sidebar bên trái + vùng nội dung bên phải.
- Khởi tạo trang con theo nhu cầu (lazy-load) => khởi động nhanh, tiết kiệm tài nguyên.
- Giữ state chia sẻ: kết nối pyodbc, danh sách DB được chọn, cấu hình JSON toàn app.
- Tích hợp lưu/đọc cấu hình qua utils.app_config (app_config.json).
"""

import logging
from typing import Optional, Dict, Any, Set
from datetime import datetime
import customtkinter as ctk
import pyodbc  # pip install pyodbc

# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
import os,sys
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)

from services.email_service import InternalEmailSender
from utils.utils import get_odbc_drivers_for_sql_server
from utils.app_config import load_config, save_config

# Các frame con
from gui.backup_page import (
    DashboardFrame,
    ConnectionFrame,
    DatabasesFrame,
    ScheduleFrame,
    RestoreFrame,
    LogsFrame,
)

logger = logging.getLogger(__name__)

# Tệp cấu hình kết nối DB
CONFIG_PATH = "app_config.json"


class DatabasePage(ctk.CTkFrame):
    """
    Trang tổng điều khiển MSSQL Backup:
      - Sidebar các mục: Dashboard / Kết nối / Lưu trữ / Database / Lịch / Backup thủ công / Restore / Logs
      - Content hiển thị page tương ứng (tạo/lưu page theo lazy-load)
      - State dùng chung giữa các page thông qua self: kết nối, config, danh sách DB...
    """
    def __init__(self, parent):
        """
        """
        super().__init__(parent)
        self.parent = parent

        # Gửi email nội bộ 
        self.email_sender = InternalEmailSender()

        # Danh sách driver ODBC khả dụng (đọc một lần)
        self.odbc_drivers = get_odbc_drivers_for_sql_server()

        # Kết nối hiện tại (nếu đã kết nối thành công từ tab "Kết nối")
        self.conn: Optional[pyodbc.Connection] = None

        # Lưu thông tin kết nối (driver, server, auth_mode, username)
        self.conn_config: Dict[str, Any] = {}

        # Đọc cấu hình JSON (tự động tạo default nếu chưa có)
        self.config: Dict[str, Any] = load_config(CONFIG_PATH)

        # Tập hợp DB đã chọn để backup (đồng bộ từ config)
        self.selected_databases: Set[str] = set(self.config.get("databases", []))

        # ------------------------- BỐ CỤC 1x2 -------------------------
        # Cột 0: sidebar, cột 1: content
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        self._build_sidebar()
        self._build_content()

        # Mặc định mở Dashboard khi vào màn hình chính
        self.show_page("Connection")

    # ======================================================================
    # Sidebar (bên trái)
    # ======================================================================
    def _build_sidebar(self):
        """Tạo sidebar với danh sách nút điều hướng và các nút thao tác nhanh."""
        self.sidebar = ctk.CTkFrame(self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_columnconfigure(0, weight=1)

        # Tiêu đề khu vực
        ctk.CTkLabel(
            self.sidebar,
            text="MSSQL Backup",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, padx=20, pady=(20, 10))

        # Danh sách các page: (text hiển thị, key nội bộ)
        self._nav_defs = [
            ("Kết nối", "Connection"),
            ("Dashboard", "Dashboard"),
            ("Database", "Databases"),
            ("Lịch Backup", "Schedule"),
            ("Restore", "Restore"),
            ("Logs", "Logs"),
        ]

        # Tạo các nút điều hướng theo danh sách trên
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        for idx, (text, key) in enumerate(self._nav_defs, start=1):
            btn = ctk.CTkButton(self.sidebar, text=text, fg_color= "transparent", command=lambda k=key: self.show_page(k))
            btn.grid(row=idx, column=0, padx=20, pady=6, sticky="ew")
            self.nav_buttons[key] = btn

        # Đẩy các nút thao tác nhanh xuống cuối
        self.sidebar.grid_rowconfigure(len(self._nav_defs) + 1, weight=1)

        # Nút thao tác nhanh (placeholder – bạn nối vào scheduler thực tế)
        self.btn_start = ctk.CTkButton(
            self.sidebar,
            text="▶ Start Scheduler",
            fg_color="#22c55e",
            hover_color="#16a34a",
            command=self._on_start,
        )
        self.btn_stop = ctk.CTkButton(
            self.sidebar,
            text="⏸ Stop Scheduler",
            fg_color="#ef4444",
            hover_color="#b91c1c",
            command=self._on_stop,
        )
        # Lưu cấu hình ra JSON
        self.btn_save = ctk.CTkButton(self.sidebar, text="💾 Lưu cấu hình", command=self.save_config)

        base = len(self._nav_defs) + 1
        self.btn_start.grid(row=base + 0, column=0, padx=20, pady=(20, 8), sticky="ew")
        self.btn_stop.grid(row=base + 1, column=0, padx=20, pady=8, sticky="ew")
        self.btn_save.grid(row=base + 2, column=0, padx=20, pady=(8, 20), sticky="ew")

    # ======================================================================
    # Content (vùng chính, lazy-load)
    # ======================================================================
    def _build_content(self):
        """Khởi tạo vùng nội dung và kho chứa trang con (lazy)."""
        self.content = ctk.CTkFrame(self)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        # Lưu các frame đã tạo để tái sử dụng (key -> frame)
        self.pages: Dict[str, ctk.CTkFrame] = {}
        self.active_key: Optional[str] = None  # page hiện đang hiển thị

    def _get_page(self, key: str) -> Optional[ctk.CTkFrame]:
        """
        Lấy (hoặc tạo) frame theo key. Chỉ tạo khi lần đầu gọi -> lazy-load.
        """
        if key in self.pages:
            return self.pages[key]

        # Tạo frame tương ứng với key yêu cầu
        if key == "Dashboard":
            page = DashboardFrame(self.content, self)
        elif key == "Connection":
            page = ConnectionFrame(self.content, self)
        elif key == "Databases":
            page = DatabasesFrame(self.content, self)
        elif key == "Schedule":
            page = ScheduleFrame(self.content, self)
        elif key == "Restore":
            page = RestoreFrame(self.content, self)
        elif key == "Logs":
            page = LogsFrame(self.content, self)
        else:
            # Không có key hợp lệ -> trả None
            logger.warning("Yêu cầu trang không hợp lệ: %s", key)
            return None

        # Đưa frame vào lưới nhưng ẩn ngay; chỉ hiển thị khi show_page()
        page.grid(row=0, column=0, sticky="nsew")
        page.grid_remove()

        # Ghi vào kho để tái sử dụng
        self.pages[key] = page
        return page

    def show_page(self, key: str):
        """
        Hiển thị trang theo key:
          - Ẩn trang hiện tại
          - Lấy/tạo trang yêu cầu
          - Hiện trang mới và cập nhật màu nút điều hướng
        """
        page = self._get_page(key)
        if not page:
            return

        # Ẩn trang cũ (nếu có)
        if self.active_key and self.active_key in self.pages:
            self.pages[self.active_key].grid_remove()
            # Màu nút cũ về trong suốt
            if self.active_key in self.nav_buttons:
                self.nav_buttons[self.active_key].configure(fg_color="transparent")

        # Hiện trang mới
        page.grid()
        self.active_key = key
        if key in self.nav_buttons:
            # Đánh dấu nút đang chọn
            self.nav_buttons[key].configure(fg_color=("gray75", "gray25"))

        logger.info("Đã chuyển sang trang: %s", key)

    # ======================================================================
    # Tiện ích chia sẻ cho các frame con
    # ======================================================================
    def add_database_for_backup(self, name: str) -> bool:
        """
        Thêm DB vào danh sách backup (set) và trả True nếu là phần tử mới
        (False nếu đã tồn tại).
        """
        if name in self.selected_databases:
            return False
        self.selected_databases.add(name)
        return True

    def timestamp_str(self) -> str:
        """Chuỗi timestamp ngắn để đóng dấu tên file backup (YYYYMMDD_HHMMSS)."""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    # ======================================================================
    # Lưu / Đọc cấu hình JSON
    # ======================================================================
    def save_config(self, silent: bool = False):
        """
        Ghi state hiện tại vào file JSON cấu hình:
          - connection (được cập nhật từ ConnectionFrame)
          - storage (backup_dir)
          - databases (từ self.selected_databases)
          - schedule (từ ScheduleFrame)
        """
        # Đồng bộ danh sách DB được chọn về mảng có thứ tự
        self.config["databases"] = sorted(self.selected_databases)

        # Ghi ra đĩa
        save_config(CONFIG_PATH, self.config)

        if not silent:
            # Thông báo nhẹ cho người dùng
            from tkinter import messagebox
            messagebox.showinfo("Cấu hình", f"Đã lưu cấu hình vào {CONFIG_PATH}")

    # ======================================================================
    # Nút nhanh (placeholder – bạn nối với scheduler thực tế)
    # ======================================================================
    def _on_start(self):
        from tkinter import messagebox
        messagebox.showinfo("Scheduler", "Start scheduler (placeholder). Hãy nối với Schedule_Auto của bạn.")

    def _on_stop(self):
        from tkinter import messagebox
        messagebox.showinfo("Scheduler", "Stop scheduler (placeholder)")
if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    root.geometry("1200x720")
    root.title("DatabasePage — Demo")
    page = DatabasePage(root)
    page.pack(fill="both", expand=True)
    root.mainloop()