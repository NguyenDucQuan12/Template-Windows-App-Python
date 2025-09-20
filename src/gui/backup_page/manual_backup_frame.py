# -*- coding: utf-8 -*-
"""
ManualBackupFrame
- Khung chạy backup ngay theo kiểu (FULL/DIFF/LOG) cho các DB đã chọn
- Ví dụ T-SQL an toàn cơ bản; bạn có thể mở rộng thêm CHECKSUM, COMPRESSION, STRIPING...
- Chạy trên thread để không chặn UI
"""
import customtkinter as ctk
from tkinter import ttk, messagebox
import threading

class ManualBackupFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Backup thủ công", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        ctk.CTkLabel(self, text="Kiểu backup:").grid(row=1, column=0, padx=(16,8), pady=6, sticky="e")
        self.cbo_type = ctk.CTkComboBox(self, values=["FULL","DIFF","LOG"], width=160)
        self.cbo_type.grid(row=1, column=1, padx=(0,8), pady=6, sticky="w")
        self.cbo_type.set("FULL")

        ctk.CTkButton(self, text="Chạy backup", command=self._run_backup).grid(row=2, column=1, padx=(0,8), pady=(8, 12), sticky="w")

        self.txt = ctk.CTkTextbox(self, width=1, height=1)
        self.txt.grid(row=3, column=0, columnspan=3, padx=16, pady=(0,16), sticky="nsew")

    def _log(self, s: str):
        self.txt.configure(state="normal"); self.txt.insert("end", s+"\n"); self.txt.see("end"); self.txt.configure(state="disabled")

    def _run_backup(self):
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Kết nối SQL Server trước.")
            return
        bdir = self.owner.config.get("storage",{}).get("backup_dir")
        if not bdir:
            messagebox.showwarning("Thiếu thông tin", "Cấu hình 'Lưu trữ' chưa có thư mục backup.")
            return
        dbs = sorted(self.owner.selected_databases)
        if not dbs:
            messagebox.showwarning("Chưa có DB", "Chưa có DB nào trong danh sách backup.")
            return
        btype = self.cbo_type.get().strip().upper()
        self.txt.configure(state="normal"); self.txt.delete("1.0","end"); self.txt.configure(state="disabled")

        def _work():
            try:
                cur = self.owner.conn.cursor()
                for db in dbs:
                    # Tạo tên file .bak/.trn đơn giản
                    if btype == "LOG":
                        # Lưu ý: chỉ chạy được nếu DB ở FULL/BULK_LOGGED
                        target = f"{bdir}{db}_LOG_{self.owner.timestamp_str()}.trn"
                        sql = "BACKUP LOG [{}] TO DISK = ? WITH INIT, SKIP, CHECKSUM, STATS=1".format(db)
                    elif btype == "DIFF":
                        target = f"{bdir}{db}_DIFF_{self.owner.timestamp_str()}.bak"
                        sql = "BACKUP DATABASE [{}] TO DISK = ? WITH DIFFERENTIAL, INIT, SKIP, CHECKSUM, STATS=1".format(db)
                    else: # FULL
                        target = f"{bdir}{db}_FULL_{self.owner.timestamp_str()}.bak"
                        sql = "BACKUP DATABASE [{}] TO DISK = ? WITH INIT, SKIP, CHECKSUM, STATS=1".format(db)
                    self._log(f"→ {db} [{btype}] => {target}")
                    cur.execute(sql, (target,))
                    self._log("   ✓ OK")
            except Exception as e:
                self._log(f"[LỖI] {e}")
            else:
                self._log("Hoàn tất.")

        threading.Thread(target=_work, daemon=True).start()