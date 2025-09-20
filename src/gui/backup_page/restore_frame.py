# -*- coding: utf-8 -*-
"""
RestoreFrame
- Khung nhập đường dẫn file FULL/DIFF/LOG và thời điểm STOPAT (tùy chọn)
- Ví dụ lệnh RESTORE cơ bản (không mạnh tay MOVE/REPLACE mặc định để an toàn)
- Bạn cần tuỳ biến theo quy trình thực tế (clone DB mới, VERIFYONLY, WITH MOVE v.v.)
"""
import customtkinter as ctk
from tkinter import messagebox
import threading

class RestoreFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        self.grid_rowconfigure(4, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Khôi phục (Restore)", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        ctk.CTkLabel(self, text="Database đích:").grid(row=1, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_db = ctk.CTkEntry(self, width=280)
        self.ent_db.grid(row=1, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkLabel(self, text="File FULL(.bak):").grid(row=2, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_full = ctk.CTkEntry(self, width=480)
        self.ent_full.grid(row=2, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkLabel(self, text="File DIFF(.bak) (tuỳ chọn):").grid(row=3, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_diff = ctk.CTkEntry(self, width=480)
        self.ent_diff.grid(row=3, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkLabel(self, text="Thư mục LOG(.trn) theo thứ tự (tuỳ chọn):").grid(row=4, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_logs = ctk.CTkEntry(self, width=480, placeholder_text="VD: D:/SQL_Backup/DB/logs/")
        self.ent_logs.grid(row=4, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkLabel(self, text="STOPAT (yyyy-mm-dd HH:MM:SS, tuỳ chọn):").grid(row=5, column=0, padx=(16,8), pady=6, sticky="e")
        self.ent_stopat = ctk.CTkEntry(self, width=280)
        self.ent_stopat.grid(row=5, column=1, padx=(0,8), pady=6, sticky="w")

        ctk.CTkButton(self, text="Thực hiện khôi phục", command=self._run_restore).grid(row=6, column=1, padx=(0,8), pady=(8,12), sticky="w")

        self.txt = ctk.CTkTextbox(self, width=1, height=1)
        self.txt.grid(row=7, column=0, columnspan=3, padx=16, pady=(0,16), sticky="nsew")

    def _log(self, s: str):
        self.txt.configure(state="normal"); self.txt.insert("end", s+"\n"); self.txt.see("end"); self.txt.configure(state="disabled")

    def _run_restore(self):
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Kết nối SQL Server trước.")
            return
        db = self.ent_db.get().strip()
        full = self.ent_full.get().strip()
        diff = self.ent_diff.get().strip() or None
        logs_dir = self.ent_logs.get().strip() or None
        stopat = self.ent_stopat.get().strip() or None
        if not db or not full:
            messagebox.showwarning("Thiếu thông tin", "Cần database đích và file FULL .bak")
            return
        self.txt.configure(state="normal"); self.txt.delete("1.0","end"); self.txt.configure(state="disabled")

        def _work():
            try:
                cur = self.owner.conn.cursor()
                self._log(f"→ RESTORE FULL vào [{db}] từ: {full}")
                cur.execute(f"RESTORE DATABASE [{db}] FROM DISK = ? WITH NORECOVERY, REPLACE", (full,))
                self._log("   ✓ FULL xong (NORECOVERY)")
                if diff:
                    self._log(f"→ RESTORE DIFF: {diff}")
                    cur.execute(f"RESTORE DATABASE [{db}] FROM DISK = ? WITH NORECOVERY", (diff,))
                    self._log("   ✓ DIFF xong (NORECOVERY)")
                if logs_dir:
                    # Gợi ý: lấy danh sách .trn theo thứ tự tên file/timestamp
                    import os
                    trns = [os.path.join(logs_dir, f) for f in sorted(os.listdir(logs_dir)) if f.lower().endswith('.trn')]
                    for trn in trns:
                        if stopat:
                            self._log(f"→ RESTORE LOG tới STOPAT {stopat}: {trn}")
                            cur.execute(f"RESTORE LOG [{db}] FROM DISK = ? WITH NORECOVERY, STOPAT = ?", (trn, stopat))
                            stopat = None  # chỉ áp dụng STOPAT cho file chứa điểm thời gian
                        else:
                            self._log(f"→ RESTORE LOG: {trn}")
                            cur.execute(f"RESTORE LOG [{db}] FROM DISK = ? WITH NORECOVERY", (trn,))
                        self._log("   ✓ LOG xong (NORECOVERY)")
                # Đưa DB về ONLINE
                self._log("→ RECOVERY")
                cur.execute(f"RESTORE DATABASE [{db}] WITH RECOVERY")
                self._log("   ✓ Hoàn tất.")
            except Exception as e:
                self._log(f"[LỖI] {e}")

        threading.Thread(target=_work, daemon=True).start()