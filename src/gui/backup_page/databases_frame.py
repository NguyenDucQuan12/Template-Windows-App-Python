# -*- coding: utf-8 -*-
"""Quản lý danh sách DB đã chọn để backup (thêm từ ConnectionFrame)."""
import customtkinter as ctk
from tkinter import ttk, messagebox

class DatabasesFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Danh sách DB cần backup", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        self.tv = ttk.Treeview(self, columns=("name",), show="headings")
        self.tv.heading("name", text="Database")
        self.tv.column("name", anchor="w", width=300)
        self.tv.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns", pady=8)

        acts = ctk.CTkFrame(self, fg_color="transparent")
        acts.grid(row=2, column=0, padx=16, pady=(0,16), sticky="ew")
        acts.grid_columnconfigure(0, weight=1)
        acts.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(acts, text="↻ Làm mới", command=self._reload).grid(row=0, column=0, padx=(0,6), sticky="ew")
        ctk.CTkButton(acts, text="🗑️ Gỡ", command=self._remove).grid(row=0, column=1, padx=(6,0), sticky="ew")

        self._reload()

    def _reload(self):
        self.tv.delete(*self.tv.get_children())
        for name in sorted(self.owner.selected_databases):
            self.tv.insert("", "end", values=(name,))

    def _remove(self):
        items = self.tv.selection()
        if not items:
            messagebox.showinfo("Chưa chọn", "Chọn DB để gỡ.")
            return
        removed = []
        for iid in items:
            name = self.tv.item(iid, "values")[0]
            if name in self.owner.selected_databases:
                self.owner.selected_databases.remove(name)
                removed.append(name)
        # cập nhật config và lưu
        self.owner.config["databases"] = sorted(self.owner.selected_databases)
        self.owner.save_config(silent = True)
        self._reload()
        if removed:
            messagebox.showinfo("Đã gỡ", "\n".join(removed))