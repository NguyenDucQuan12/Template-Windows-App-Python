# -*- coding: utf-8 -*-
"""Khung xem log cơ bản (tuỳ bạn nối file/DB log)."""
import customtkinter as ctk

class LogsFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Logs", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")
        box = ctk.CTkTextbox(self)
        box.grid(row=1, column=0, padx=16, pady=16, sticky="nsew")
        box.insert("end", "• Nối nguồn log thực tế vào đây (file/DB).\n")
        box.configure(state="disabled")