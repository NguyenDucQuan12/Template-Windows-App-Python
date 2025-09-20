# -*- coding: utf-8 -*-
"""
ScheduleFrame
- Khung cấu hình lịch backup (FULL/DIFF/LOG) theo CRON string (ví dụ)
- Validate chuỗi CRON ở mức cơ bản (5 trường: m h dom mon dow)
- Cập nhật config JSON ngay khi người dùng bấm Lưu

Lưu ý: Bạn có thể thay thế bằng UI time‑picker hoặc scheduler thực tế của bạn.
"""
import customtkinter as ctk
from tkinter import messagebox
import re

_CRON_RE = re.compile(r"^\s*([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s*$")

class ScheduleFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Lịch Backup", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        ctk.CTkLabel(self, text="CRON FULL:").grid(row=1, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_full = ctk.CTkEntry(self, width=320)
        self.ent_full.grid(row=1, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkLabel(self, text="CRON DIFF:").grid(row=2, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_diff = ctk.CTkEntry(self, width=320)
        self.ent_diff.grid(row=2, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkLabel(self, text="CRON LOG:").grid(row=3, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_log = ctk.CTkEntry(self, width=320)
        self.ent_log.grid(row=3, column=1, padx=(0,8), pady=6, sticky="w")

        # Nút lưu
        ctk.CTkButton(self, text="💾 Lưu lịch", command=self._on_save).grid(row=4, column=1, padx=(0,8), pady=(10, 16), sticky="w")

        # Fill từ config hiện tại
        sch = self.owner.config.get("schedule", {})
        self.ent_full.insert(0, sch.get("full", "0 0 * * 0"))
        self.ent_diff.insert(0, sch.get("diff", "30 0 * * 1-6"))
        self.ent_log.insert(0, sch.get("log",  "*/15 * * * *"))

    def _validate_cron(self, s: str) -> bool:
        return bool(_CRON_RE.match(s or ""))

    def _on_save(self):
        full = self.ent_full.get().strip()
        diff = self.ent_diff.get().strip()
        log  = self.ent_log.get().strip()
        # Validate đơn giản
        if not (self._validate_cron(full) and self._validate_cron(diff) and self._validate_cron(log)):
            messagebox.showwarning("Chuỗi CRON không hợp lệ", "Vui lòng nhập CRON 5 trường: phút giờ ngày-tháng tháng thứ.")
            return
        self.owner.config.setdefault("schedule", {})
        self.owner.config["schedule"].update({"full": full, "diff": diff, "log": log})
        self.owner.save_config(silent = True)
        messagebox.showinfo("Đã lưu", "Đã lưu lịch backup vào cấu hình.")