# -*- coding: utf-8 -*-
"""
Kịch bản Backup (gộp Storage + Schedule + Manual)
- Phụ thuộc DatabasePage (owner_page): cần self.conn, self.selected_databases, self.config, self.save_config()
- Lưu cấu hình THEO TỪNG CSDL trong app_config.json:
    config["per_db"][<db_name>] = {
        "backup_dir": "D:/SQL_Backup/",
        "schedule": {
            "full": "0 0 * * 0",
            "diff": "30 0 * * 1-6",
            "log":  "*/15 * * * *"
        }
    }
- Khi chọn DB từ combobox -> tự nạp lại cấu hình, hiển thị vào UI
"""

import os
import re
import threading
import customtkinter as ctk
from tkinter import ttk, messagebox, filedialog
from typing import Dict, Any, Optional

_CRON_RE = re.compile(r"^\s*([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s*$")

class ScheduleFrame(ctk.CTkFrame):
    """
    Frame "Kịch bản Backup":
    1) Chọn CSDL
    2) Chọn thư mục lưu trữ + nút kiểm tra quyền ghi từ SQL Server
    3) Cài đặt lịch Full/Diff/Log (CRON 5 trường)
    4) Backup thủ công cho CSDL đã chọn
    5) Lưu cấu hình theo từng CSDL vào app_config.json
    """

    def __init__(self, parent, owner_page):
        """
        parent: frame cha (content area)
        owner_page: DatabasePage (chia sẻ state)
        """
        super().__init__(parent)
        self.owner = owner_page

        # --- State tạm cho UI ---
        self.current_db: Optional[str] = None    # CSDL đang chọn trong combobox

        # Đảm bảo nhánh per_db tồn tại trong config
        self.owner.config.setdefault("per_db", {})  # kiểu: { db_name: {...} }

        # Bố cục 1 cột: tiêu đề -> khối chọn DB -> khối lưu trữ -> khối lịch -> khối backup tay
        self.grid_rowconfigure(6, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # ---------------- Tiêu đề ----------------
        ctk.CTkLabel(self, text="Kịch bản Backup", font=ctk.CTkFont(size=18, weight="bold"))\
            .grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        # ---------------- Chọn CSDL ----------------
        self._build_db_selector(row=1)

        # ---------------- Khu lưu trữ ----------------
        self._build_storage(row=2)

        # ---------------- Khu lịch backup ----------------
        self._build_schedule(row=3)

        # ---------------- Khu backup thủ công ----------------
        self._build_manual_backup(row=4)

        # Dòng dưới cùng: ghi chú/trạng thái
        self.status_box = ctk.CTkTextbox(self, height=100)
        self.status_box.grid(row=5, column=0, padx=16, pady=(6, 16), sticky="nsew")
        self._log("• Chọn CSDL, cấu hình thư mục lưu trữ, lịch backup, hoặc chạy backup thủ công.")

        # Khởi tạo giá trị ban đầu (chọn DB đầu tiên nếu có)
        self._init_db_selection()

    # ======================================================================
    # UI builders
    # ======================================================================

    def _build_db_selector(self, row: int):
        """Khối chọn DB bằng combobox."""
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(wrap, text="Chọn CSDL:").grid(row=0, column=0, padx=(12, 8), pady=8, sticky="e")
        self.cbo_db = ctk.CTkComboBox(wrap, values=sorted(self.owner.selected_databases), width=260,
                                      command=lambda _: self._on_change_db())
        self.cbo_db.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        # Nút cập nhật danh sách DB khi vừa thêm/xóa ở trang khác
        ctk.CTkButton(wrap, text="↻ Nạp danh sách", command=self._reload_db_list).grid(
            row=0, column=2, padx=8, pady=8, sticky="w"
        )

    def _build_storage(self, row: int):
        """Khối cấu hình thư mục lưu trữ + kiểm tra quyền ghi."""
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(wrap, text="Thư mục lưu trữ (trên SQL Server):").grid(row=0, column=0, padx=(12, 8), pady=8, sticky="e")
        self.ent_dir = ctk.CTkEntry(wrap, width=460, placeholder_text=r"VD: D:\SQL_Backup\ hoặc \\fileserver\share\sqlbackup")
        self.ent_dir.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        # Chọn thư mục cục bộ (để tiện copy đường dẫn) — lưu ý: SQL Server service cần thấy đường dẫn này
        ctk.CTkButton(wrap, text="Chọn (cục bộ)", command=self._choose_local_dir).grid(row=0, column=2, padx=8, pady=8, sticky="w")

        # Kiểm tra quyền ghi
        ctk.CTkButton(wrap, text="Kiểm tra quyền ghi từ SQL Server", command=self._test_write_perm).grid(
            row=1, column=1, padx=8, pady=(0, 8), sticky="w"
        )

        # Lưu khi rời focus
        self.ent_dir.bind("<FocusOut>", lambda _: self._persist_for_current_db())

    def _build_schedule(self, row: int):
        """Khối cấu hình lịch backup (CRON)."""
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(wrap, text="Lịch FULL (CRON):").grid(row=0, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_full = ctk.CTkEntry(wrap, width=320)
        self.ent_full.grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Lịch DIFF (CRON):").grid(row=1, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_diff = ctk.CTkEntry(wrap, width=320)
        self.ent_diff.grid(row=1, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Lịch LOG (CRON):").grid(row=2, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_log = ctk.CTkEntry(wrap, width=320)
        self.ent_log.grid(row=2, column=1, padx=8, pady=6, sticky="w")

        # Nút lưu riêng (cũng lưu khi đổi DB)
        ctk.CTkButton(wrap, text="💾 Lưu lịch", command=self._save_schedule).grid(
            row=3, column=1, padx=8, pady=(6, 8), sticky="w"
        )

    def _build_manual_backup(self, row: int):
        """Khối backup thủ công cho DB đang chọn."""
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")

        ctk.CTkLabel(wrap, text="Backup thủ công cho CSDL đã chọn:", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=12, pady=(10, 6), sticky="w"
        )

        ctk.CTkLabel(wrap, text="Kiểu:").grid(row=1, column=0, padx=(12, 8), pady=6, sticky="e")
        self.cbo_type = ctk.CTkComboBox(wrap, values=["FULL", "DIFF", "LOG"], width=120)
        self.cbo_type.grid(row=1, column=1, padx=8, pady=6, sticky="w")
        self.cbo_type.set("FULL")

        ctk.CTkButton(wrap, text="Chạy backup", command=self._run_manual_backup).grid(
            row=1, column=2, padx=8, pady=6, sticky="w"
        )

    # ======================================================================
    # DB selection & persistence
    # ======================================================================

    def _init_db_selection(self):
        """Chọn DB đầu tiên nếu có; nạp cấu hình của DB vào form."""
        dbs = sorted(self.owner.selected_databases)
        if not dbs:
            self._log("• Chưa có DB trong danh sách backup. Vào tab 'Database' để thêm.")
            return
        # Nếu combobox chưa set, set DB đầu tiên
        if not self.cbo_db.get():
            self.cbo_db.set(dbs[0])
        self._on_change_db()

    def _reload_db_list(self):
        """Nút '↻ Nạp danh sách': cập nhật combobox theo selected_databases."""
        values = sorted(self.owner.selected_databases)
        self.cbo_db.configure(values=values)
        if values:
            if self.cbo_db.get() not in values:
                self.cbo_db.set(values[0])
            self._on_change_db()
        else:
            self.cbo_db.set("")
            self.current_db = None
            self._clear_form()

    def _on_change_db(self):
        """Khi đổi DB trong combobox -> load cấu hình từ per_db và hiển thị."""
        self.current_db = self.cbo_db.get().strip() or None
        if not self.current_db:
            self._clear_form()
            return

        # Đảm bảo có khung cấu hình cho DB này
        per_db = self.owner.config.setdefault("per_db", {})
        db_cfg: Dict[str, Any] = per_db.setdefault(self.current_db, {})
        db_cfg.setdefault("backup_dir", None)
        db_cfg.setdefault("schedule", {"full": "0 0 * * 0", "diff": "30 0 * * 1-6", "log": "*/15 * * * *"})

        # Hiển thị
        self.ent_dir.delete(0, "end")
        if db_cfg.get("backup_dir"):
            self.ent_dir.insert(0, db_cfg["backup_dir"])

        sch = db_cfg.get("schedule", {})
        self.ent_full.delete(0, "end"); self.ent_full.insert(0, sch.get("full", "0 0 * * 0"))
        self.ent_diff.delete(0, "end"); self.ent_diff.insert(0, sch.get("diff", "30 0 * * 1-6"))
        self.ent_log.delete(0, "end");  self.ent_log.insert(0, sch.get("log",  "*/15 * * * *"))

    def _clear_form(self):
        """Xoá nội dung form khi không có DB."""
        self.ent_dir.delete(0, "end")
        self.ent_full.delete(0, "end")
        self.ent_diff.delete(0, "end")
        self.ent_log.delete(0, "end")

    def _persist_for_current_db(self):
        """Ghi lại 'backup_dir' cho DB hiện tại khi rời focus."""
        if not self.current_db:
            return
        path = self.ent_dir.get().strip() or None
        self.owner.config.setdefault("per_db", {}).setdefault(self.current_db, {}).update({"backup_dir": path})
        self.owner.save_config(silent=True)  # ghi không popup
        self._log(f"• Đã lưu thư mục lưu trữ cho [{self.current_db}].")

    # ======================================================================
    # Storage actions
    # ======================================================================

    def _choose_local_dir(self):
        """Chọn thư mục cục bộ (để tiện copy dán). Lưu ý: SQL Server phải nhìn thấy đường dẫn này."""
        path = filedialog.askdirectory(title="Chọn thư mục (cục bộ)")
        if path:
            if not path.endswith(os.sep):
                path += os.sep
            self.ent_dir.delete(0, "end")
            self.ent_dir.insert(0, path)
            self._persist_for_current_db()

    def _test_write_perm(self):
        """Kiểm tra SQL Server có quyền ghi vào thư mục không (DB đang chọn)."""
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Vào tab 'Kết nối' để kết nối SQL Server trước.")
            return
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Hãy chọn CSDL trước khi kiểm tra.")
            return
        target = self.ent_dir.get().strip()
        if not target:
            messagebox.showwarning("Thiếu thông tin", "Nhập thư mục đích trên SQL Server.")
            return

        self._clear_status()

        def _work():
            try:
                cur = self.owner.conn.cursor()
                # B1: xp_dirtree
                can_xp = True
                try:
                    cur.execute("EXEC master..xp_dirtree ?,1,1", (target,))
                    self._log(f"[OK] xp_dirtree thấy thư mục: {target}")
                except Exception as e:
                    can_xp = False
                    self._log(f"[CẢNH BÁO] xp_dirtree lỗi: {e}")

                # B2: xp_cmdshell thử tạo file
                if can_xp:
                    test_file = os.path.join(target, "perm_test.txt")
                    try:
                        cur.execute("EXEC master..xp_cmdshell 'echo OK> " + test_file.replace('\"', '\"\"') + "'")
                        self._log(f"[OK] Tạo file test: {test_file}")
                        cur.execute("EXEC master..xp_cmdshell 'del " + test_file.replace('\"', '\"\"') + "'")
                        self._log("[OK] Xoá file test.")
                        self._log("[KẾT LUẬN] SQL Server CÓ quyền ghi.")
                        return
                    except Exception as e:
                        self._log(f"[CẢNH BÁO] xp_cmdshell tạo file thất bại: {e}")

                # B3: Fallback bằng BACKUP COPY_ONLY database hiện tại vào file nhỏ
                bak = os.path.join(target, f"{self.current_db}_PERM_TEST_COPYONLY.bak")
                try:
                    cur.execute(
                        f"""
                        BACKUP DATABASE [{self.current_db}]
                        TO DISK = ?
                        WITH COPY_ONLY, INIT, SKIP, CHECKSUM, STATS=1
                        """,
                        (bak,)
                    )
                    self._log(f"[OK] Tạo file .bak kiểm tra: {bak}")
                    try:
                        cur.execute("EXEC master..xp_cmdshell 'del " + bak.replace('\"', '\"\"') + "'")
                        self._log("[OK] Xoá file .bak.")
                    except Exception as de:
                        self._log(f"[CHÚ Ý] Không xoá được .bak qua xp_cmdshell: {de}")
                    self._log("[KẾT LUẬN] SQL Server CÓ quyền ghi (qua BACKUP).")
                except Exception as e:
                    self._log(f"[THẤT BẠI] Không xác minh được quyền ghi: {e}")
                    self._log("• Bật xp_cmdshell (nếu phù hợp) hoặc cấp quyền ghi cho service account.")
            except Exception as e:
                self._log(f"[LỖI] {e}")

        threading.Thread(target=_work, daemon=True).start()

    # ======================================================================
    # Schedule actions
    # ======================================================================

    def _save_schedule(self):
        """Lưu CRON cho DB hiện tại."""
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Hãy chọn CSDL trước khi lưu lịch.")
            return
        full = self.ent_full.get().strip()
        diff = self.ent_diff.get().strip()
        log  = self.ent_log.get().strip()

        # Validate cơ bản: 5 trường
        for s, nm in ((full, "FULL"), (diff, "DIFF"), (log, "LOG")):
            if not _CRON_RE.match(s or ""):
                messagebox.showwarning("CRON không hợp lệ", f"Lịch {nm} chưa đúng định dạng CRON (5 trường).")
                return

        self.owner.config.setdefault("per_db", {}).setdefault(self.current_db, {})\
            .setdefault("schedule", {}).update({"full": full, "diff": diff, "log": log})

        self.owner.save_config(silent=True)
        messagebox.showinfo("Đã lưu", f"Đã lưu lịch backup cho [{self.current_db}].")

    # ======================================================================
    # Manual backup
    # ======================================================================

    def _run_manual_backup(self):
        """Chạy backup thủ công cho DB hiện chọn theo kiểu FULL/DIFF/LOG."""
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Kết nối SQL Server trước.")
            return
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Chọn CSDL trước khi backup.")
            return

        # Lấy thư mục lưu riêng của DB này
        per_db = self.owner.config.get("per_db", {})
        db_cfg = per_db.get(self.current_db, {})
        bdir = db_cfg.get("backup_dir")
        if not bdir:
            messagebox.showwarning("Thiếu thông tin", "Chưa có thư mục lưu trữ cho CSDL này.")
            return

        btype = self.cbo_type.get().strip().upper()
        self._clear_status()

        def _work():
            try:
                cur = self.owner.conn.cursor()

                # Tạo tên file
                ts = self.owner.timestamp_str() if hasattr(self.owner, "timestamp_str") else "YYYYMMDD_HHMMSS"
                if btype == "LOG":
                    target = f"{bdir}{self.current_db}_LOG_{ts}.trn"
                    sql = f"BACKUP LOG [{self.current_db}] TO DISK = ? WITH INIT, SKIP, CHECKSUM, STATS=1"
                elif btype == "DIFF":
                    target = f"{bdir}{self.current_db}_DIFF_{ts}.bak"
                    sql = f"BACKUP DATABASE [{self.current_db}] TO DISK = ? WITH DIFFERENTIAL, INIT, SKIP, CHECKSUM, STATS=1"
                else:
                    target = f"{bdir}{self.current_db}_FULL_{ts}.bak"
                    sql = f"BACKUP DATABASE [{self.current_db}] TO DISK = ? WITH INIT, SKIP, CHECKSUM, STATS=1"

                self._log(f"→ [{self.current_db}] [{btype}] => {target}")
                cur.execute(sql, (target,))
                self._log("   ✓ Hoàn tất.")
            except Exception as e:
                self._log(f"[LỖI] {e}")

        threading.Thread(target=_work, daemon=True).start()

    # ======================================================================
    # Helpers
    # ======================================================================

    def _log(self, s: str):
        """Ghi log xuống hộp trạng thái cuối trang."""
        self.status_box.configure(state="normal")
        self.status_box.insert("end", s + "\n")
        self.status_box.see("end")
        self.status_box.configure(state="disabled")

    def _clear_status(self):
        self.status_box.configure(state="normal")
        self.status_box.delete("1.0", "end")
        self.status_box.configure(state="disabled")
