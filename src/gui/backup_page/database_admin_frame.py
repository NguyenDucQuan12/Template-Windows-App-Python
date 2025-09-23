# -*- coding: utf-8 -*-
"""
DatabaseAdminFrame (sử dụng kết nối cũ: self.owner.conn, KHÔNG nhúng Dashboard)
-------------------------------------------------------------------------------
- Sidebar: Recovery Model / Kiểm tra thư mục / Retention / Orphan Users / DBCC CHECKDB
- Content: mỗi mục là 1 sub-frame, lazy-load.
- Tất cả thao tác nặng chạy nền (thread) để UI không đơ.
- Dùng lại kết nối có sẵn từ self.owner.conn (pyodbc.Connection).
- Không kiểm tra kết nối ở __init__; chỉ kiểm tra trước khi thực thi tác vụ.
- (Tuỳ chọn) Nếu owner có hàm emit_dashboard_event(ev:dict) thì sẽ phát sự kiện realtime;
  còn nếu không có, sẽ bỏ qua (không lỗi).
"""

import os
import time
import queue
import threading
import datetime as dt
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk
from tkinter import ttk, filedialog, messagebox


SYSTEM_DATABASES = {"master", "model", "msdb", "tempdb"}


# =====================================================================
# Các tiện ích kết nối/SQL an toàn
# =====================================================================

def _test_connection(conn) -> bool:
    """
    Kiểm tra nhanh kết nối có còn dùng được không (SELECT 1).
    - Không gọi ở __init__; chỉ gọi ngay trước khi thao tác.
    """
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        return True
    except Exception:
        return False


def run_sql_safe(conn, sql: str, params: Tuple = (), autocommit: bool = True) -> Tuple[bool, str, Optional[list]]:
    """
    Thực thi 1 câu SQL an toàn:
    - Bật autocommit tạm thời (nếu cần), khôi phục sau.
    - Trả (ok, message, rows) thay vì raise để UI hiển thị thân thiện.
    - rows: fetchall() nếu có (SELECT), ngược lại là None.
    """
    cur = None
    prev = getattr(conn, "autocommit", False)
    try:
        conn.autocommit = autocommit
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = None
        try:
            rows = cur.fetchall()
        except Exception:
            rows = None
        return True, "OK", rows
    except Exception as e:
        return False, f"{e}", None
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.autocommit = prev
        except Exception:
            pass


# =====================================================================
# Frame chính: KHÔNG có Dashboard bên trong
# =====================================================================

class DatabaseAdminFrame(ctk.CTkFrame):
    """
    Khung quản trị CSDL:
    - Bên trái: Sidebar chọn module
    - Bên phải: Content hiển thị module (lazy-load)
    - Dùng kết nối self.owner.conn (pyodbc.Connection) do trang chủ cung cấp.
    """

    def __init__(self, parent, owner_page):
        """
        Args:
            parent: widget cha
            owner_page: trang cha (phải có self.conn là pyodbc.Connection sau khi đăng nhập/kết nối)
        """
        super().__init__(parent)
        self.owner = owner_page

        # Layout 1x2
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Sidebar
        self.sidebar = ctk.CTkFrame(self)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(10, weight=1)

        ctk.CTkLabel(self.sidebar, text="Quản trị CSDL", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 8)
        )
        self.btn_recovery  = ctk.CTkButton(self.sidebar, text="♻ Recovery Model", command=self._open_recovery)
        self.btn_perm      = ctk.CTkButton(self.sidebar, text="🗂 Kiểm tra thư mục", command=self._open_perm)
        self.btn_retention = ctk.CTkButton(self.sidebar, text="🧹 Retention cleanup", command=self._open_retention)
        self.btn_orphan    = ctk.CTkButton(self.sidebar, text="👤 Orphan users", command=self._open_orphan)
        self.btn_checkdb   = ctk.CTkButton(self.sidebar, text="🩺 DBCC CHECKDB", command=self._open_checkdb)

        for i, b in enumerate([self.btn_recovery, self.btn_perm, self.btn_retention, self.btn_orphan, self.btn_checkdb], start=1):
            b.grid(row=i, column=0, padx=12, pady=6, sticky="ew")

        # Content holder
        self.content = ctk.CTkFrame(self)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self._modules: Dict[str, ctk.CTkFrame] = {}

        # Mặc định mở Recovery
        self._open_recovery()

    # ---------------- helpers ----------------

    def _get_conn(self):
        """
        Lấy kết nối hiện tại từ owner.
        - Không kiểm tra ở __init__ để tránh báo sớm.
        - Ngay trước khi thao tác sẽ test SELECT 1.
        """
        conn = getattr(self.owner, "conn", None)
        if conn is None:
            raise RuntimeError("Chưa thiết lập kết nối SQL Server (self.owner.conn=None).")
        if not _test_connection(conn):
            raise RuntimeError("Kết nối SQL hiện tại không hợp lệ/đã đóng. Vui lòng kết nối lại.")
        return conn

    def _emit_event(self, ev: Dict[str, Any]):
        """
        (Tuỳ chọn) Phát sự kiện realtime ra trang chủ/Trang Dashboard nếu owner có hàm emit_dashboard_event().
        Nếu không có thì bỏ qua.
        """
        try:
            if hasattr(self.owner, "emit_dashboard_event") and callable(self.owner.emit_dashboard_event):
                self.owner.emit_dashboard_event(ev)
        except Exception:
            pass

    def _show_module(self, key: str, factory):
        """Lazy-load subframe, hiển thị duy nhất 1 module."""
        for w in self.content.winfo_children():
            w.grid_forget()
        if key not in self._modules:
            self._modules[key] = factory()
        self._modules[key].grid(row=0, column=0, sticky="nsew")

    # ---------------- open module ----------------
    def _open_recovery(self):
        self._show_module("recovery", lambda: RecoveryModelFrame(self.content, self))
    def _open_perm(self):
        self._show_module("perm", lambda: FolderPermissionFrame(self.content, self))
    def _open_retention(self):
        self._show_module("retention", lambda: RetentionCleanupFrame(self.content, self))
    def _open_orphan(self):
        self._show_module("orphan", lambda: OrphanUsersFrame(self.content, self))
    def _open_checkdb(self):
        self._show_module("checkdb", lambda: CheckDBFrame(self.content, self))


# =====================================================================
# Module: Recovery Model
# =====================================================================

class RecoveryModelFrame(ctk.CTkFrame):
    """
    Đổi Recovery Model hàng loạt (SIMPLE/FULL/BULK_LOGGED).
    - Liệt kê DB + trạng thái + size + thời điểm backup gần nhất.
    - Chọn nhiều DB -> sinh Script hoặc Thực thi.
    - Cảnh báo khi chuyển về SIMPLE (phá chain log).
    """

    def __init__(self, parent, admin: DatabaseAdminFrame):
        super().__init__(parent)
        self.admin = admin
        self._queue = queue.Queue()
        self._rows: List[Dict[str, Any]] = []

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Recovery Model", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="w"
        )

        tool = ctk.CTkFrame(self)
        tool.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        tool.grid_columnconfigure(5, weight=1)

        self.ent_search = ctk.CTkEntry(tool, width=220, placeholder_text="Tìm DB…")
        self.ent_search.grid(row=0, column=0, padx=(8, 6), pady=6)
        ctk.CTkButton(tool, text="Lọc", command=self._apply_filter).grid(row=0, column=1, padx=4, pady=6)
        ctk.CTkButton(tool, text="↻ Nạp lại", command=self._reload).grid(row=0, column=2, padx=4, pady=6)

        self.cmb_model = ctk.CTkComboBox(tool, values=["SIMPLE", "FULL", "BULK_LOGGED"], width=160)
        self.cmb_model.set("SIMPLE")
        self.cmb_model.grid(row=0, column=3, padx=8, pady=6)

        ctk.CTkButton(tool, text="Sinh Script", command=lambda: self._apply(False)).grid(row=0, column=4, padx=4, pady=6)
        ctk.CTkButton(tool, text="Thực thi", fg_color="#22c55e", hover_color="#16a34a",
                      command=lambda: self._apply(True)).grid(row=0, column=5, padx=8, pady=6, sticky="e")

        # Bảng
        self.tree = ttk.Treeview(self, columns=("name", "state", "recovery", "size_mb", "last_full", "last_diff", "last_log"),
                                 show="headings", selectmode="extended")
        for col, text, w, anchor in [
            ("name", "Database", 200, "w"),
            ("state", "Trạng thái", 110, "center"),
            ("recovery", "Recovery", 120, "center"),
            ("size_mb", "Size (MB)", 90, "e"),
            ("last_full", "FULL", 140, "center"),
            ("last_diff", "DIFF", 140, "center"),
            ("last_log", "LOG", 140, "center"),
        ]:
            self.tree.heading(col, text=text)
            self.tree.column(col, width=w, anchor=anchor)
        self.tree.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="nsew")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=2, column=1, sticky="ns", pady=(0, 8))

        # Log
        self.txt = ctk.CTkTextbox(self, height=140)
        self.txt.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="nsew")

        self._reload()

    def _log(self, s: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", s.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _reload(self):
        self._log("Đang tải danh sách DB ...")
        self.tree.delete(*self.tree.get_children())

        def worker():
            try:
                conn = self.admin._get_conn()
            except Exception as e:
                self._queue.put(("ERR", str(e))); return

            sql = r"""
;WITH size_cte AS (
  SELECT database_id, CAST(SUM(size)*8.0/1024 AS DECIMAL(18,1)) AS size_mb
  FROM sys.master_files GROUP BY database_id
),
last_full AS (
  SELECT database_name, MAX(backup_finish_date) AS last_full
  FROM msdb.dbo.backupset WHERE type = 'D' GROUP BY database_name
),
last_diff AS (
  SELECT database_name, MAX(backup_finish_date) AS last_diff
  FROM msdb.dbo.backupset WHERE type = 'I' GROUP BY database_name
),
last_log AS (
  SELECT database_name, MAX(backup_finish_date) AS last_log
  FROM msdb.dbo.backupset WHERE type = 'L' GROUP BY database_name
)
SELECT d.name, d.state_desc, d.recovery_model_desc, s.size_mb, f.last_full, i.last_diff, l.last_log
FROM sys.databases d
LEFT JOIN size_cte s ON s.database_id = d.database_id
LEFT JOIN last_full f ON f.database_name = d.name
LEFT JOIN last_diff i ON i.database_name = d.name
LEFT JOIN last_log l ON l.database_name = d.name
ORDER BY d.name;
"""
            ok, msg, rows = run_sql_safe(conn, sql)
            if not ok:
                self._queue.put(("ERR", msg)); return
            out = []
            for name, st, rec, size_mb, lf, ld, ll in rows or []:
                def fmt(x):
                    return x.strftime("%Y-%m-%d %H:%M:%S") if x else ""
                out.append({
                    "name": name, "state": st, "recovery": rec,
                    "size_mb": float(size_mb or 0.0),
                    "last_full": fmt(lf), "last_diff": fmt(ld), "last_log": fmt(ll)
                })
            self._queue.put(("DATA", out))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_reload)

    def _poll_reload(self):
        try:
            tag, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_reload); return
        if tag == "ERR":
            self._log(f"[LỖI] {payload}")
            return
        if tag == "DATA":
            self._rows = payload
            for r in self._rows:
                self.tree.insert("", "end", values=(r["name"], r["state"], r["recovery"],
                                                    f'{r["size_mb"]:,.1f}', r["last_full"], r["last_diff"], r["last_log"]))
            self._log(f"Đã tải {len(self._rows)} DB.")

    def _apply_filter(self):
        key = (self.ent_search.get() or "").strip().lower()
        self.tree.delete(*self.tree.get_children())
        for r in self._rows:
            if not key or key in r["name"].lower():
                self.tree.insert("", "end", values=(r["name"], r["state"], r["recovery"],
                                                    f'{r["size_mb"]:,.1f}', r["last_full"], r["last_diff"], r["last_log"]))

    def _selected_dbs(self) -> List[str]:
        names = []
        for iid in self.tree.selection():
            val = self.tree.set(iid, "name")
            if val:
                names.append(val)
        return names

    def _apply(self, do_change: bool):
        target = self.cmb_model.get().strip().upper()
        dbs = [d for d in self._selected_dbs() if d not in SYSTEM_DATABASES]
        if not dbs:
            messagebox.showinfo("Chưa chọn", "Chọn ít nhất 1 DB (không gồm master/model/msdb/tempdb).")
            return
        if target == "SIMPLE":
            if not messagebox.askokcancel("Cảnh báo", "Đổi về SIMPLE sẽ phá chuỗi LOG. Tiếp tục?"):
                return

        scripts = [f"ALTER DATABASE [{d}] SET RECOVERY {target};" for d in dbs]
        self._log("===== SCRIPT =====")
        for s in scripts:
            self._log(s)
        self._log("==================")

        if not do_change:
            messagebox.showinfo("Script đã sinh", "Bạn có thể copy & chạy trên SSMS.")
            return

        def worker():
            ok_all = True
            try:
                conn = self.admin._get_conn()
            except Exception as e:
                self._queue.put(("LOG", f"[LỖI] {e}")); self._queue.put(("DONE", False)); return
            for s in scripts:
                ok, msg, _ = run_sql_safe(conn, s)
                if ok:
                    self._queue.put(("LOG", f"[OK] {s}"))
                else:
                    ok_all = False
                    self._queue.put(("LOG", f"[LỖI] {s}\n    → {msg}"))
            self._queue.put(("DONE", ok_all))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_apply)

    def _poll_apply(self):
        try:
            tag, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_apply); return
        if tag == "LOG":
            self._log(payload); self.after(50, self._poll_apply)
        elif tag == "DONE":
            self._log("Hoàn tất.")
            # Gửi event realtime (nếu trang chủ có đăng ký)
            self.admin._emit_event({
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "db": "(multiple)", "type": f"RECOVERY→{self.cmb_model.get()}",
                "status": "OK" if payload else "FAIL", "note": ""
            })
            if payload:
                messagebox.showinfo("OK", "Đã đổi Recovery Model.")


# =====================================================================
# Module: Kiểm tra thư mục backup (backup 'model')
# =====================================================================

class FolderPermissionFrame(ctk.CTkFrame):
    """
    Kiểm tra quyền ghi thư mục backup bằng cách BACKUP DATABASE [model] (nhẹ).
    - Không đụng DB lớn.
    - Có log chi tiết; thử xp_dirtree; xoá file test nếu xp_cmdshell bật.
    """

    def __init__(self, parent, admin: DatabaseAdminFrame):
        super().__init__(parent)
        self.admin = admin

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Kiểm tra thư mục backup (backup 'model')",
                     font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        form = ctk.CTkFrame(self)
        form.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Thư mục đích:").grid(row=0, column=0, padx=(8, 6), pady=6, sticky="e")
        self.ent_dir = ctk.CTkEntry(form, placeholder_text=r"VD: E:\SQL_Backup\ hoặc \\server\share\path\\", width=520)
        self.ent_dir.grid(row=0, column=1, padx=(0, 6), pady=6, sticky="ew")
        ctk.CTkButton(form, text="Chọn…", command=self._browse).grid(row=0, column=2, padx=6, pady=6)
        ctk.CTkButton(form, text="Kiểm tra", fg_color="#22c55e", hover_color="#16a34a", command=self._run).grid(row=0, column=3, padx=(6, 8), pady=6)

        self.txt = ctk.CTkTextbox(self, height=220)
        self.txt.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")

    def _browse(self):
        path = filedialog.askdirectory(title="Chọn thư mục backup")
        if path:
            if not path.endswith("\\"):
                path += "\\"
            self.ent_dir.delete(0, "end"); self.ent_dir.insert(0, path)

    def _log(self, s: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", s.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _run(self):
        base = (self.ent_dir.get() or "").strip()
        if not base:
            messagebox.showwarning("Thiếu thông tin", "Nhập thư mục backup.")
            return
        if not (base.endswith("\\") or base.endswith("/")):
            base += "\\"
            self.ent_dir.delete(0, "end"); self.ent_dir.insert(0, base)

        self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.configure(state="disabled")
        self._log("=== KIỂM TRA QUYỀN GHI BẰNG DB 'model' ===")

        def worker():
            try:
                conn = self.admin._get_conn()
            except Exception as e:
                self._log(f"[LỖI] {e}"); return

            prev = getattr(conn, "autocommit", False)
            cur = None
            try:
                conn.autocommit = True
                cur = conn.cursor()

                # 1) Thử xp_dirtree (nếu tắt thì chỉ cảnh báo, không fail)
                try:
                    cur.execute("EXEC master..xp_dirtree ?, 1, 1;", (base,))
                    self._log(f"[OK] xp_dirtree thấy thư mục: {base}")
                except Exception as e:
                    self._log(f"[CHÚ Ý] xp_dirtree lỗi (bỏ qua): {e}")

                # 2) Tạo file backup test
                test_name = f"MODEL_PERM_{os.getpid()}_{int(time.time())}.bak"
                test_path = base + test_name
                self._log(f"→ Sinh file test: {test_path}")

                # 3) BACKUP DATABASE [model] (nhẹ + COPY_ONLY + COMPRESSION)
                try:
                    cur.execute("""
                        BACKUP DATABASE [model]
                        TO DISK = ?
                        WITH COPY_ONLY, COMPRESSION, INIT, SKIP, CHECKSUM, STATS = 1;
                    """, (test_path,))
                    self._log("[OK] Ghi file test thành công.")
                    # (Tuỳ chọn) phát sự kiện realtime cho Dashboard
                    self.admin._emit_event({
                        "ts": dt.datetime.now().isoformat(timespec="seconds"),
                        "db": "(model)", "type": "TEST-WRITE", "status": "OK", "note": test_name
                    })
                except Exception as e:
                    self._log(f"[THẤT BẠI] BACKUP model: {e}")
                    self.admin._emit_event({
                        "ts": dt.datetime.now().isoformat(timespec="seconds"),
                        "db": "(model)", "type": "TEST-WRITE", "status": "FAIL", "note": str(e)
                    })
                    return

                # 4) Xoá file test nếu xp_cmdshell bật (không bắt buộc)
                try:
                    del_cmd = f'del "{test_path.replace("\"", "\"\"")}"'
                    cur.execute("EXEC master..xp_cmdshell ?", (del_cmd,))
                    self._log("[OK] Đã xoá file test bằng xp_cmdshell.")
                except Exception:
                    self._log("[CHÚ Ý] xp_cmdshell tắt/không xoá được — bạn có thể xoá tay file test nếu muốn.")

                self._log("[KẾT LUẬN] SQL Server CÓ thể ghi vào thư mục.")
            except Exception as e:
                self._log(f"[LỖI] {e}")
            finally:
                try:
                    if cur: cur.close()
                except Exception: pass
                try:
                    conn.autocommit = prev
                except Exception: pass

        threading.Thread(target=worker, daemon=True).start()


# =====================================================================
# Module: Retention cleanup
# =====================================================================

class RetentionCleanupFrame(ctk.CTkFrame):
    """
    Xóa file backup quá hạn theo số ngày giữ lại.
    - Có Dry-Run: liệt kê file sẽ xóa, KHÔNG xóa thật.
    - Pattern đuôi file: .bak, .dif, .trn (mặc định, có thể chỉnh).
    """

    def __init__(self, parent, admin: DatabaseAdminFrame):
        super().__init__(parent)
        self.admin = admin

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Retention cleanup", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="w"
        )

        form = ctk.CTkFrame(self)
        form.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(form, text="Thư mục gốc:").grid(row=0, column=0, padx=(8, 6), pady=6, sticky="e")
        self.ent_base = ctk.CTkEntry(form, placeholder_text=r"VD: E:\SQL_Backup\ hoặc \\server\share\path\\", width=520)
        self.ent_base.grid(row=0, column=1, padx=(0, 6), pady=6, sticky="ew")
        ctk.CTkButton(form, text="Chọn…", command=self._browse).grid(row=0, column=2, padx=6, pady=6)

        ctk.CTkLabel(form, text="Ngày giữ lại:").grid(row=0, column=3, padx=(12, 6), pady=6, sticky="e")
        self.ent_days = ctk.CTkEntry(form, width=80)
        self.ent_days.insert(0, "14")
        self.ent_days.grid(row=0, column=4, padx=(0, 6), pady=6)

        ctk.CTkLabel(form, text="Pattern:").grid(row=0, column=5, padx=(12, 6), pady=6, sticky="e")
        self.ent_patterns = ctk.CTkEntry(form, width=160)
        self.ent_patterns.insert(0, ".bak,.dif,.trn")
        self.ent_patterns.grid(row=0, column=6, padx=(0, 6), pady=6)

        self.chk_dry = ctk.CTkCheckBox(form, text="Dry-Run (không xóa thật)")
        self.chk_dry.grid(row=0, column=7, padx=(12, 8), pady=6)
        self.chk_dry.select()

        ctk.CTkButton(form, text="Thực thi", fg_color="#f59e0b", hover_color="#b45309",
                      command=self._run).grid(row=0, column=8, padx=(8, 8), pady=6)

        self.txt = ctk.CTkTextbox(self, height=240)
        self.txt.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="nsew")

    def _browse(self):
        path = filedialog.askdirectory(title="Chọn thư mục gốc")
        if path:
            if not path.endswith("\\"):
                path += "\\"
            self.ent_base.delete(0, "end"); self.ent_base.insert(0, path)

    def _log(self, s: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", s.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _run(self):
        import fnmatch
        base = (self.ent_base.get() or "").strip()
        if not base:
            messagebox.showwarning("Thiếu thông tin", "Chọn thư mục gốc.")
            return
        try:
            days = int((self.ent_days.get() or "0").strip())
            if days < 0:
                raise ValueError
        except Exception:
            messagebox.showwarning("Sai dữ liệu", "Số ngày giữ lại phải là số nguyên ≥ 0.")
            return
        pats = [p.strip().lower() for p in self.ent_patterns.get().split(",") if p.strip()]
        dry = bool(self.chk_dry.get())

        self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.configure(state="disabled")
        self._log(f"=== RETENTION: base={base}, keep_days={days}, patterns={pats}, dry_run={dry} ===")

        def worker():
            now = time.time()
            cutoff = now - days * 86400
            cand: List[str] = []
            deleted = 0

            for root, _, files in os.walk(base):
                for f in files:
                    fn = f.lower()
                    if not any(fn.endswith(p) for p in pats):
                        continue
                    path = os.path.join(root, f)
                    try:
                        st = os.stat(path)
                        if st.st_mtime < cutoff:
                            cand.append(path)
                    except Exception as e:
                        self._log(f"[CẢNH BÁO] Không đọc được: {path} → {e}")

            if dry:
                self._log("• DRY-RUN: Sẽ xóa các file sau:")
                for p in cand:
                    self._log("  - " + p)
                self._log(f"Tổng {len(cand)} file.")
                return

            for p in cand:
                try:
                    os.remove(p)
                    deleted += 1
                    self._log("[OK] Xóa: " + p)
                except Exception as e:
                    self._log(f"[LỖI] Không xóa được {p} → {e}")

            self._log(f"Hoàn tất. Đã xóa {deleted}/{len(cand)} file.")
            # (Tuỳ chọn) phát sự kiện nhẹ cho Dashboard
            self.admin._emit_event({
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "db": "(retention)", "type": "CLEANUP", "status": "OK", "note": f"deleted={deleted}"
            })

        threading.Thread(target=worker, daemon=True).start()


# =====================================================================
# Module: Orphan Users
# =====================================================================

class OrphanUsersFrame(ctk.CTkFrame):
    """
    Dò user mồ côi (db user không map được login).
    - Liệt kê theo DB user.
    - Sinh script gợi ý ALTER USER ... WITH LOGIN ... (không tự thực thi).
    """

    def __init__(self, parent, admin: DatabaseAdminFrame):
        super().__init__(parent)
        self.admin = admin
        self._rows: List[Tuple[str, str]] = []  # (db, user)

        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Orphan Users", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="w"
        )

        tool = ctk.CTkFrame(self)
        tool.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")
        ctk.CTkButton(tool, text="↻ Quét orphan users", command=self._scan).grid(row=0, column=0, padx=6, pady=6)
        ctk.CTkButton(tool, text="Sinh Script gợi ý", command=self._gen_script).grid(row=0, column=1, padx=6, pady=6)

        self.tree = ttk.Treeview(self, columns=("db", "user"), show="headings", selectmode="extended")
        self.tree.heading("db", text="Database"); self.tree.column("db", width=200, anchor="w")
        self.tree.heading("user", text="DB User"); self.tree.column("user", width=240, anchor="w")
        self.tree.grid(row=2, column=0, padx=12, pady=(0, 8), sticky="nsew")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set); vsb.grid(row=2, column=1, sticky="ns", pady=(0, 8))

        self.txt = ctk.CTkTextbox(self, height=200)
        self.txt.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="nsew")

    def _log(self, s: str):
        self.txt.configure(state="normal"); self.txt.insert("end", s.rstrip() + "\n"); self.txt.see("end"); self.txt.configure(state="disabled")

    def _scan(self):
        # Xoá kết quả cũ
        self.tree.delete(*self.tree.get_children()); self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.configure(state="disabled")
        self._rows.clear()
        self._log("Đang quét orphan users trên tất cả DB user ...")

        def worker():
            try:
                conn = self.admin._get_conn()
            except Exception as e:
                self._log(f"[LỖI] {e}"); return

            ok, msg, rows = run_sql_safe(conn, "SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name;")
            if not ok:
                self._log(f"[LỖI] {msg}"); return
            dbs = [r[0] for r in (rows or [])]

            query = r"""
SELECT dp.name AS db_user
FROM sys.database_principals dp
LEFT JOIN sys.server_principals sp ON dp.sid = sp.sid
WHERE dp.type IN ('S','U') AND dp.principal_id > 4 AND sp.sid IS NULL
ORDER BY dp.name;
"""
            for db in dbs:
                try:
                    ok, msg, rows = run_sql_safe(conn, f"USE [{db}]; {query}")
                    if not ok:
                        self._log(f"[LỖI] {db}: {msg}"); continue
                    for (u,) in rows or []:
                        self._rows.append((db, u))
                        self.tree.insert("", "end", values=(db, u))
                except Exception as e:
                    self._log(f"[LỖI] {db}: {e}")

            self._log(f"Hoàn tất. Tìm thấy {len(self._rows)} orphan user.")
            # (tuỳ chọn) phát event
            self.admin._emit_event({
                "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "db": "(orphan-scan)", "type": "SCAN", "status": "OK", "note": f"found={len(self._rows)}"
            })

        threading.Thread(target=worker, daemon=True).start()

    def _gen_script(self):
        if not self._rows:
            messagebox.showinfo("Trống", "Chưa có orphan để sinh script.")
            return
        self._log("===== GỢI Ý SCRIPT =====")
        self._log("-- Thay [server_login] thành login phù hợp rồi chạy trên SSMS")
        for db, u in self._rows:
            self._log(f"USE [{db}]; ALTER USER [{u}] WITH LOGIN = [server_login];")
        self._log("========================")
        self.admin._emit_event({
            "ts": dt.datetime.now().isoformat(timespec="seconds"),
            "db": "(orphan)", "type": "SCRIPT", "status": "OK", "note": f"{len(self._rows)} users"
        })


# =====================================================================
# Module: DBCC CHECKDB
# =====================================================================

class CheckDBFrame(ctk.CTkFrame):
    """
    DBCC CHECKDB: chọn DB + chế độ QUICK (PHYSICAL_ONLY) hoặc FULL.
    - Chạy nền, log tóm tắt; không khoá UI.
    """

    def __init__(self, parent, admin: DatabaseAdminFrame):
        super().__init__(parent)
        self.admin = admin

        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="DBCC CHECKDB", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=12, pady=(12, 6), sticky="w"
        )

        form = ctk.CTkFrame(self)
        form.grid(row=1, column=0, padx=12, pady=(0, 6), sticky="ew")

        ctk.CTkLabel(form, text="Database:").grid(row=0, column=0, padx=(8, 6), pady=6, sticky="e")
        self.cmb_db = ctk.CTkComboBox(form, values=[], width=220)
        self.cmb_db.grid(row=0, column=1, padx=(0, 12), pady=6)

        ctk.CTkLabel(form, text="Chế độ:").grid(row=0, column=2, padx=(8, 6), pady=6, sticky="e")
        self.cmb_mode = ctk.CTkComboBox(form, values=["QUICK (PHYSICAL_ONLY)", "FULL"], width=220)
        self.cmb_mode.set("QUICK (PHYSICAL_ONLY)")
        self.cmb_mode.grid(row=0, column=3, padx=(0, 12), pady=6)

        ctk.CTkButton(form, text="↻ Nạp DB", command=self._load_dbs).grid(row=0, column=4, padx=6, pady=6)
        ctk.CTkButton(form, text="Thực thi", fg_color="#22c55e", hover_color="#16a34a", command=self._run).grid(row=0, column=5, padx=6, pady=6)

        self.txt = ctk.CTkTextbox(self, height=260)
        self.txt.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="nsew")

        self._load_dbs()

    def _log(self, s: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", s.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")

    def _load_dbs(self):
        # Chỉ kiểm tra kết nối tại thời điểm người dùng bấm "↻ Nạp DB" hoặc init
        try:
            conn = self.admin._get_conn()
        except Exception as e:
            messagebox.showwarning("Chưa kết nối", str(e))
            return
        ok, msg, rows = run_sql_safe(conn, "SELECT name FROM sys.databases WHERE database_id > 4 ORDER BY name;")
        if not ok:
            messagebox.showerror("Lỗi", msg); return
        vals = [r[0] for r in (rows or [])] or [""]
        self.cmb_db.configure(values=vals); self.cmb_db.set(vals[0])

    def _run(self):
        # Kiểm tra kết nối ngay trước khi thực thi
        try:
            conn = self.admin._get_conn()
        except Exception as e:
            messagebox.showwarning("Chưa kết nối", str(e)); return

        db = self.cmb_db.get().strip()
        if not db:
            messagebox.showwarning("Thiếu thông tin", "Chọn database.")
            return
        is_quick = "quick" in self.cmb_mode.get().lower()

        self.txt.configure(state="normal"); self.txt.delete("1.0", "end"); self.txt.configure(state="disabled")
        self._log(f"=== DBCC CHECKDB ON [{db}] mode={'PHYSICAL_ONLY' if is_quick else 'FULL'} ===")

        def worker():
            sql = f"DBCC CHECKDB (N'{db}') WITH NO_INFOMSGS"
            if is_quick:
                sql += ", PHYSICAL_ONLY"
            sql += ";"
            ok, msg, _ = run_sql_safe(conn, sql)
            if ok:
                self._log("[OK] DBCC CHECKDB hoàn tất (NO_INFOMSGS).")
                self.admin._emit_event({
                    "ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "db": db, "type": "CHECKDB", "status": "OK", "note": "NO_INFOMSGS"
                })
            else:
                self._log(f"[LỖI] {msg}")
                self.admin._emit_event({
                    "ts": dt.datetime.now().isoformat(timespec="seconds"),
                    "db": db, "type": "CHECKDB", "status": "FAIL", "note": msg
                })

        threading.Thread(target=worker, daemon=True).start()
