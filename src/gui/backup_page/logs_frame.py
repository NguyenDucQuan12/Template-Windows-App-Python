# -*- coding: utf-8 -*-
"""
Hiển thị lịch sử backup đọc từ các file log do PS1 ghi:
<BackupDir>\\_TaskLogs\\<DB>.log
Mỗi dòng:
  YYYY-MM-DDTHH:MM:SS|<Database>|<Type>|OK|<file1;file2;...>
"""

import os
import datetime as dt
import customtkinter as ctk
from tkinter import ttk, messagebox

class LogsFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        """
        parent: khung container
        owner_page: DatabasePage (chứa self.selected_databases, self.config)
        """
        super().__init__(parent)
        self.owner = owner_page

        # Lấy danh sách DB (chuyển set -> list, sort)
        self.all_dbs = sorted(list(self.owner.selected_databases)) if hasattr(self.owner, "selected_databases") else []

        # UI layout
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Lịch sử sao lưu CSDL", font=ctk.CTkFont(size=16, weight="bold"))\
            .grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        # Thanh lọc DB
        top = ctk.CTkFrame(self)
        top.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        top.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(top, text="CSDL:").grid(row=0, column=0, padx=(4, 6), pady=6, sticky="e")
        values = ["(Tất cả)"] + self.all_dbs
        self.cbo_db = ctk.CTkComboBox(top, values=values, width=220, command=lambda _: self.reload())
        self.cbo_db.grid(row=0, column=1, padx=(0, 8), pady=6, sticky="w")
        self.cbo_db.set("(Tất cả)")

        ctk.CTkButton(top, text="↻ Làm mới", command=self.reload).grid(row=0, column=2, padx=(6, 6), pady=6, sticky="w")

        # Bảng dữ liệu
        self.tree = ttk.Treeview(
            self, columns=("ts","db","type","status","files"),
            show="headings", height=18
        )
        self.tree.heading("ts", text="THỜI GIAN")
        self.tree.heading("db", text="DATABASE")
        self.tree.heading("type", text="LOẠI")
        self.tree.heading("status", text="KẾT QUẢ")
        self.tree.heading("files", text="TỆP TẠO")
        # Set width
        self.tree.column("ts", width=180, anchor="w")
        self.tree.column("db", width=160, anchor="w")
        self.tree.column("type", width=70, anchor="w")
        self.tree.column("status", width=80, anchor="w")
        self.tree.column("files", width=600, anchor="w")
        self.tree.grid(row=2, column=0, padx=12, pady=(0, 10), sticky="nsew")

        # Scrollbar
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=2, column=1, sticky="ns", pady=(0, 10))

        # Lần đầu nạp
        self.reload()

    # ------------------- Helpers -------------------

    def _get_per_db_backup_dir(self, db_name: str):
        """Lấy đường dẫn backup_dir của DB từ config."""
        per_db = self.owner.config.get("per_db", {})
        return (per_db.get(db_name, {}) or {}).get("backup_dir")

    def _iter_log_files(self, selected_db: str):
        """
        Lấy danh sách tệp log cần đọc:
        - Nếu selected_db == '(Tất cả)': duyệt mọi DB đang có trong config và có thư mục _TaskLogs/DB.log
        - Ngược lại: chỉ log của DB đó
        Trả về list các tuple (db_name, log_path)
        """
        candidates = []
        per_db = self.owner.config.get("per_db", {})

        def add_if_exists(db):
            bdir = (per_db.get(db, {}) or {}).get("backup_dir")
            if not bdir: return
            log_path = os.path.join(bdir.rstrip("\\/"), "_TaskLogs", f"{db}.log")
            if os.path.isfile(log_path):
                candidates.append((db, log_path))

        if selected_db and selected_db != "(Tất cả)":
            add_if_exists(selected_db)
        else:
            # duyệt toàn bộ DB trong cấu hình (not just selected_databases)
            for db in sorted(per_db.keys()):
                add_if_exists(db)
        return candidates

    def _parse_line(self, line: str):
        """
        Parse 1 dòng log -> (ts_dt, ts_str, db, typ, status, files)
        Trả None nếu không hợp lệ.
        """
        line = line.strip()
        if not line or "|" not in line:
            return None
        parts = line.split("|", 4)
        if len(parts) < 5:
            return None
        ts_s, db, typ, status, files = parts
        # parse time ISO
        try:
            ts_dt = dt.datetime.fromisoformat(ts_s)
        except Exception:
            # fallback cho chuỗi ko chuẩn
            try:
                ts_dt = dt.datetime.strptime(ts_s, "%Y-%m-%d %H:%M:%S")
            except Exception:
                return None
        return (ts_dt, ts_s, db, typ, status, files)

    # ------------------- Public API -------------------

    def reload(self):
        """Đọc log từ các DB (theo combobox), gộp và hiển thị giảm dần theo thời gian."""
        # Xác định DB filter
        sel_db = self.cbo_db.get().strip()

        # Xóa bảng
        for i in self.tree.get_children():
            self.tree.delete(i)

        # Gom dữ liệu
        items = []
        for db, log_path in self._iter_log_files(sel_db):
            try:
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        row = self._parse_line(line)
                        if row:
                            items.append(row)
            except Exception as e:
                messagebox.showwarning("Đọc log lỗi", f"DB [{db}] - không thể đọc file:\n{log_path}\n\n{e}")

        # Sắp xếp theo thời gian giảm dần
        items.sort(key=lambda r: r[0], reverse=True)

        # Đổ dữ liệu
        for ts_dt, ts_s, db, typ, status, files in items:
            self.tree.insert("", "end", values=(ts_s, db, typ, status, files))
