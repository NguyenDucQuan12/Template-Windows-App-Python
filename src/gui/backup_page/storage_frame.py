# -*- coding: utf-8 -*-
"""
StorageFrame
- Người dùng chọn thư mục đích BACKUP mà **SQL Server** nhìn thấy (ổ cục bộ của server hoặc UNC)
- Nút kiểm tra quyền ghi từ phía SQL Server:
    + Ưu tiên dùng xp_dirtree + xp_cmdshell để tạo/xoá file test
    + Fallback: BACKUP COPY_ONLY database master -> tạo file .bak nhỏ để kiểm tra quyền ghi
- Khi người dùng nhập/thay đổi thư mục -> cập nhật config JSON
"""
import os
import customtkinter as ctk
from tkinter import messagebox, filedialog
import threading

class StorageFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Cấu hình Lưu trữ", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        ctk.CTkLabel(self, text="Thư mục lưu trên SQL Server:").grid(row=1, column=0, padx=(16,8), pady=8, sticky="e")
        self.ent_dir = ctk.CTkEntry(self, width=460, placeholder_text=r"VD: D:\\SQL_Backup\\ hoặc \\fileserver\\share\\sqlbackup")
        self.ent_dir.grid(row=1, column=1, padx=(0,8), pady=8, sticky="w")
        # Load từ config nếu có
        if self.owner.config["storage"].get("backup_dir"):
            self.ent_dir.insert(0, self.owner.config["storage"]["backup_dir"])

        self.btn_browse = ctk.CTkButton(self, text="Chọn (cục bộ)", command=self._on_browse_local)
        self.btn_browse.grid(row=1, column=2, padx=8, pady=8, sticky="w")

        self.btn_test = ctk.CTkButton(self, text="Kiểm tra quyền ghi (từ SQL Server)", command=self._on_test_write)
        self.btn_test.grid(row=2, column=1, padx=8, pady=(0,12), sticky="w")

        self.txt = ctk.CTkTextbox(self, width=1, height=1)
        self.txt.grid(row=3, column=0, columnspan=3, padx=16, pady=(0,16), sticky="nsew")
        self._log("• Hãy nhập thư mục mà SQL Server nhìn thấy (ổ server/UNC).")

        # Lưu khi người dùng rời focus
        self.ent_dir.bind("<FocusOut>", lambda e: self._persist())

    # --------------- helpers ---------------
    def _persist(self):
        path = self.ent_dir.get().strip() or None
        self.owner.config["storage"]["backup_dir"] = path
        self.owner.save_config(silent = True)

    def _log(self, msg: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _on_browse_local(self):
        path = filedialog.askdirectory(title="Chọn thư mục (cục bộ)")
        if path:
            if not path.endswith(os.sep):
                path += os.sep
            self.ent_dir.delete(0, "end")
            self.ent_dir.insert(0, path)
            self._persist()

    def _on_test_write(self):
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Vào tab 'Kết nối' để kết nối SQL Server trước.")
            return
        target = self.ent_dir.get().strip()
        if not target:
            messagebox.showwarning("Thiếu thông tin", "Nhập thư mục đích trên SQL Server.")
            return

        self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.configure(state="disabled")

        def _test():
            try:
                cur = self.owner.conn.cursor()
                # Bước 1: thử xp_dirtree
                can_xp = True
                try:
                    cur.execute("EXEC master..xp_dirtree ?,1,1", (target,))
                    self._log(f"[OK] xp_dirtree thấy thư mục: {target}")
                except Exception as e:
                    can_xp = False
                    self._log(f"[CẢNH BÁO] xp_dirtree lỗi: {e}")
                # Bước 2: nếu có xp_cmdshell -> tạo file test
                if can_xp:
                    test_file = os.path.join(target, "perm_test.txt")
                    try:
                        cur.execute("EXEC master..xp_cmdshell 'echo OK> " + test_file.replace('"','""') + "'")
                        self._log(f"[OK] Tạo file test: {test_file}")
                        cur.execute("EXEC master..xp_cmdshell 'del " + test_file.replace('"','""') + "'")
                        self._log("[OK] Xoá file test.")
                        self._log("[KẾT LUẬN] SQL Server CÓ quyền ghi.")
                        return
                    except Exception as e:
                        self._log(f"[CẢNH BÁO] xp_cmdshell tạo file thất bại: {e}")
                # Bước 3: fallback bằng BACKUP COPY_ONLY master
                bak = os.path.join(target, "perm_test_master_copyonly.bak")
                try:
                    cur.execute(
                        """
                        BACKUP DATABASE master
                        TO DISK = ?
                        WITH COPY_ONLY, INIT, SKIP, CHECKSUM, STATS=1
                        """,
                        (bak,)
                    )
                    self._log(f"[OK] Tạo file .bak kiểm tra: {bak}")
                    try:
                        cur.execute("EXEC master..xp_cmdshell 'del " + bak.replace('"','""') + "'")
                        self._log("[OK] Xoá file .bak.")
                    except Exception as de:
                        self._log(f"[CHÚ Ý] Không xoá được .bak qua xp_cmdshell: {de}")
                    self._log("[KẾT LUẬN] SQL Server CÓ quyền ghi (thông qua BACKUP).")
                except Exception as e:
                    self._log(f"[THẤT BẠI] Không xác minh được quyền ghi: {e}")
                    self._log("• Bật xp_cmdshell (nếu phù hợp) hoặc cấp quyền ghi cho service account.")
            except Exception as e:
                self._log(f"[LỖI] {e}")

        threading.Thread(target=_test, daemon=True).start()