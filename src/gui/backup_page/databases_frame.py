# -*- coding: utf-8 -*-
"""
DatabaseManagementFrame
-----------------------
Giao diện quản lý Database (SQL Server) với các chức năng:
- Liệt kê danh sách DB (name, state, recovery, size, owner, ngày tạo, backup gần nhất)
- Tìm kiếm/lọc theo tên
- Chọn nhiều DB và đổi Recovery Model: SIMPLE / FULL / BULK_LOGGED
- Sinh T-SQL trước khi thực thi (tùy chọn)
- Chạy nền (thread) để UI không bị đơ
- Xử lý lỗi cẩn thận + cảnh báo các trường hợp rủi ro

Yêu cầu:
- self.owner phải có thuộc tính `conn` (pyodbc.Connection) đã kết nối tới SQL Server
- Nếu chưa kết nối: các thao tác sẽ cảnh báo và dừng
"""

import customtkinter as ctk
from tkinter import ttk, messagebox
import threading
import queue
import datetime
from typing import List, Dict, Any, Optional

SYSTEM_DATABASES = {"master", "model", "msdb", "tempdb"}

from gui.backup_page.database_admin_frame import DatabaseAdminFrame


class DatabasesFrame(ctk.CTkFrame):
    """
    Frame quản lý database ở mức cơ bản (Recovery Model).
    Bạn có thể gắn vào trang Database hiện tại (ví dụ: thay cho DatabasePage, hoặc là tab con).
    """

    def __init__(self, parent, owner_page):
        """
        Args:
            parent: widget cha (CTkFrame/CTk)
            owner_page: đối tượng trang cha có `.conn` (pyodbc) để query SQL Server
        """
        super().__init__(parent)

        self.admin_frame = DatabaseAdminFrame(self, owner_page)   # self có .conn
        self.admin_frame.pack(fill="both", expand=True)

        
        # self.owner = owner_page

        # # Hàng đợi kết quả để truyền dữ liệu từ thread về UI
        # self._queue = queue.Queue()

        # # Bộ nhớ tạm danh sách DB đã tải, hỗ trợ lọc
        # self._db_rows: List[Dict[str, Any]] = []

        # # Dựng giao diện
        # self._build_ui()

        # # Tải dữ liệu ban đầu
        # self._reload_databases()

    # ---------------------------------------------------------------------
    # UI
    # ---------------------------------------------------------------------
    def _build_ui(self):
        """Tạo layout gồm thanh công cụ, bảng DB, khung trạng thái & chi tiết."""
        self.grid_rowconfigure(2, weight=1)  # bảng DB giãn
        self.grid_columnconfigure(0, weight=1)

        # Thanh tiêu đề
        title = ctk.CTkLabel(self, text="Quản lý Database (Recovery Model)", font=ctk.CTkFont(size=18, weight="bold"))
        title.grid(row=0, column=0, padx=12, pady=(12, 6), sticky="w")

        # Thanh công cụ (search, reload, actions)
        toolbar = ctk.CTkFrame(self)
        toolbar.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        toolbar.grid_columnconfigure(4, weight=1)

        ctk.CTkLabel(toolbar, text="Tìm kiếm:").grid(row=0, column=0, padx=(8, 6), pady=6, sticky="e")
        self.ent_search = ctk.CTkEntry(toolbar, width=220, placeholder_text="Nhập tên DB...")
        self.ent_search.grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")
        self.ent_search.bind("<Return>", lambda _: self._apply_filter())

        ctk.CTkButton(toolbar, text="Lọc", command=self._apply_filter).grid(row=0, column=2, padx=4, pady=6, sticky="w")
        ctk.CTkButton(toolbar, text="↻ Nạp lại", command=self._reload_databases).grid(row=0, column=3, padx=4, pady=6, sticky="w")

        # Khoảng trống giãn
        ctk.CTkLabel(toolbar, text="").grid(row=0, column=4, sticky="ew")

        # Nút thao tác Recovery Model
        ctk.CTkButton(toolbar, text="Đổi → SIMPLE", command=lambda: self._change_recovery_model("SIMPLE"))\
            .grid(row=0, column=5, padx=4, pady=6, sticky="e")
        ctk.CTkButton(toolbar, text="Đổi → FULL", command=lambda: self._change_recovery_model("FULL"))\
            .grid(row=0, column=6, padx=4, pady=6, sticky="e")
        ctk.CTkButton(toolbar, text="Đổi → BULK_LOGGED", command=lambda: self._change_recovery_model("BULK_LOGGED"))\
            .grid(row=0, column=7, padx=(4, 8), pady=6, sticky="e")

        # Bảng DB (ttk.Treeview vì customtkinter chưa có TreeView riêng)
        self.tree = ttk.Treeview(self, columns=(
            "name", "state", "recovery", "size_mb", "owner", "create_date", "last_full", "last_diff", "last_log"
        ), show="headings", selectmode="extended")
        # Đặt tiêu đề cột
        self.tree.heading("name", text="Database")
        self.tree.heading("state", text="Trạng thái")
        self.tree.heading("recovery", text="Recovery")
        self.tree.heading("size_mb", text="Size (MB)")
        self.tree.heading("owner", text="Owner")
        self.tree.heading("create_date", text="Ngày tạo")
        self.tree.heading("last_full", text="FULL gần nhất")
        self.tree.heading("last_diff", text="DIFF gần nhất")
        self.tree.heading("last_log", text="LOG gần nhất")
        # Đặt độ rộng cột
        self.tree.column("name", width=180, anchor="w")
        self.tree.column("state", width=100, anchor="center")
        self.tree.column("recovery", width=120, anchor="center")
        self.tree.column("size_mb", width=90, anchor="e")
        self.tree.column("owner", width=120, anchor="w")
        self.tree.column("create_date", width=140, anchor="center")
        self.tree.column("last_full", width=160, anchor="center")
        self.tree.column("last_diff", width=160, anchor="center")
        self.tree.column("last_log", width=160, anchor="center")

        # Gắn scrollbar
        scroll_y = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll_y.set)
        self.tree.grid(row=2, column=0, padx=(12, 0), pady=6, sticky="nsew")
        scroll_y.grid(row=2, column=0, padx=(0, 8), pady=6, sticky="nse")

        # Khung dưới: chi tiết + console log
        bottom = ctk.CTkFrame(self)
        bottom.grid(row=3, column=0, padx=12, pady=(4, 12), sticky="nsew")
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_rowconfigure(1, weight=1)

        self.lbl_hint = ctk.CTkLabel(
            bottom,
            text=(
                "Gợi ý: Chọn một/multiple DB trong bảng rồi bấm nút đổi Recovery.\n"
                "- Đổi từ FULL → SIMPLE sẽ phá vỡ chuỗi LOG (cảnh báo).\n"
                "- Không thao tác trên system DB (master/model/msdb/tempdb)."
            ),
            anchor="w", justify="left"
        )
        self.lbl_hint.grid(row=0, column=0, padx=8, pady=(6, 4), sticky="ew")

        self.txt_status = ctk.CTkTextbox(bottom, height=140)
        self.txt_status.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="nsew")

    # ---------------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------------
    def _log(self, msg: str):
        """Ghi log vào hộp trạng thái."""
        self.txt_status.configure(state="normal")
        self.txt_status.insert("end", msg.rstrip() + "\n")
        self.txt_status.see("end")
        self.txt_status.configure(state="disabled")

    def _clear_log(self):
        self.txt_status.configure(state="normal")
        self.txt_status.delete("1.0", "end")
        self.txt_status.configure(state="disabled")

    def _get_selected_db_names(self) -> List[str]:
        """Lấy danh sách tên DB đang chọn trong Treeview."""
        sel = []
        for iid in self.tree.selection():
            name = self.tree.set(iid, "name")
            if name:
                sel.append(name)
        return sel

    # ---------------------------------------------------------------------
    # Data loading
    # ---------------------------------------------------------------------
    def _reload_databases(self):
        """Nạp lại danh sách DB và đổ vào bảng (chạy trong thread)."""
        if not getattr(self.owner, "conn", None):
            messagebox.showwarning("Chưa kết nối", "Vui lòng kết nối SQL Server trước.")
            return

        self._clear_log()
        self._log("Đang tải danh sách database ...")
        self.tree.delete(*self.tree.get_children())

        def worker():
            try:
                rows = self._query_databases()
                # Đưa dữ liệu về main thread
                self._queue.put(("DATA", rows))
            except Exception as e:
                self._queue.put(("ERR", str(e)))

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_queue_reload)

    def _poll_queue_reload(self):
        """Đọc hàng đợi để cập nhật bảng sau khi thread tải xong."""
        try:
            tag, payload = self._queue.get_nowait()
        except queue.Empty:
            # chưa có gì, lặp lại
            self.after(100, self._poll_queue_reload)
            return

        if tag == "DATA":
            self._db_rows = payload
            self._populate_tree(self._db_rows)
            self._log(f"Đã tải {len(self._db_rows)} database.")
        elif tag == "ERR":
            self._log(f"[LỖI] Không tải được CSDL: {payload}")
            messagebox.showerror("Lỗi tải dữ liệu", str(payload))

    def _populate_tree(self, rows: List[Dict[str, Any]]):
        """Đưa dữ liệu vào Treeview sau khi nạp."""
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", values=(
                r.get("name"),
                r.get("state_desc"),
                r.get("recovery_model_desc"),
                f'{r.get("size_mb", 0):,.1f}',
                r.get("owner_name", ""),
                r.get("create_date_str", ""),
                r.get("last_full_str", ""),
                r.get("last_diff_str", ""),
                r.get("last_log_str", ""),
            ))

    def _apply_filter(self):
        """Lọc theo tên DB (simple contains)."""
        key = (self.ent_search.get() or "").strip().lower()
        if not key:
            self._populate_tree(self._db_rows); return
        filt = [r for r in self._db_rows if key in r.get("name", "").lower()]
        self._populate_tree(filt)

    # ---------------------------------------------------------------------
    # SQL queries
    # ---------------------------------------------------------------------
    def _query_databases(self) -> List[Dict[str, Any]]:
        """
        Truy vấn sys.databases + msdb.backupset để lấy:
        - name, state_desc, recovery_model_desc, size_mb, owner, create_date
        - ngày backup gần nhất: FULL/DIFF/LOG
        """
        conn = self.owner.conn
        cur = conn.cursor()

        # Kích thước DB (MB) = SUM(size pages) * 8 KB / 1024
        sql = r"""
;WITH size_cte AS (
  SELECT database_id, CAST(SUM(size)*8.0/1024 AS DECIMAL(18,1)) AS size_mb
  FROM sys.master_files
  GROUP BY database_id
),
last_full AS (
  SELECT database_name, MAX(backup_finish_date) AS last_full
  FROM msdb.dbo.backupset
  WHERE type = 'D'
  GROUP BY database_name
),
last_diff AS (
  SELECT database_name, MAX(backup_finish_date) AS last_diff
  FROM msdb.dbo.backupset
  WHERE type = 'I'
  GROUP BY database_name
),
last_log AS (
  SELECT database_name, MAX(backup_finish_date) AS last_log
  FROM msdb.dbo.backupset
  WHERE type = 'L'
  GROUP BY database_name
)
SELECT
  d.name,
  d.state_desc,
  d.recovery_model_desc,
  s.size_mb,
  SUSER_SNAME(d.owner_sid) AS owner_name,
  d.create_date,
  f.last_full,
  i.last_diff,
  l.last_log
FROM sys.databases d
LEFT JOIN size_cte s ON s.database_id = d.database_id
LEFT JOIN last_full f ON f.database_name = d.name
LEFT JOIN last_diff i ON i.database_name = d.name
LEFT JOIN last_log l ON l.database_name = d.name
ORDER BY d.name;
"""
        cur.execute(sql)
        rows = []
        for (name, state_desc, recovery_model_desc, size_mb, owner_name, create_date, last_full, last_diff, last_log) in cur.fetchall():
            def fmt_dt(dt):
                return dt.strftime("%Y-%m-%d %H:%M:%S") if isinstance(dt, datetime.datetime) else ""
            rows.append({
                "name": name,
                "state_desc": state_desc,
                "recovery_model_desc": recovery_model_desc,
                "size_mb": float(size_mb or 0),
                "owner_name": owner_name or "",
                "create_date_str": fmt_dt(create_date),
                "last_full_str": fmt_dt(last_full),
                "last_diff_str": fmt_dt(last_diff),
                "last_log_str": fmt_dt(last_log),
            })
        cur.close()
        return rows

    # ---------------------------------------------------------------------
    # Actions: Change Recovery Model
    # ---------------------------------------------------------------------
    def _change_recovery_model(self, target_model: str):
        """
        Đổi Recovery Model cho các DB đã chọn.
        - target_model: "SIMPLE", "FULL", "BULK_LOGGED"
        - Cảnh báo khi đổi FULL → SIMPLE (mất chuỗi log)
        - Bỏ qua system DB
        - Có tùy chọn "Chỉ sinh script" trước khi chạy
        """
        if not getattr(self.owner, "conn", None):
            messagebox.showwarning("Chưa kết nối", "Hãy kết nối SQL Server trước."); return

        selected = self._get_selected_db_names()
        if not selected:
            messagebox.showinfo("Chưa chọn", "Vui lòng chọn ít nhất 1 database trong bảng."); return

        # Lọc bỏ system DB
        targets = [db for db in selected if db not in SYSTEM_DATABASES]
        skipped = [db for db in selected if db in SYSTEM_DATABASES]
        if not targets:
            messagebox.showwarning("Không hợp lệ", "Không thao tác Recovery trên system DB (master/model/msdb/tempdb).")
            return
        if skipped:
            self._log(f"[BỎ QUA] System DB: {', '.join(skipped)}")

        # Cảnh báo rủi ro khi đổi sang SIMPLE
        if target_model.upper() == "SIMPLE":
            if not messagebox.askokcancel(
                "Cảnh báo",
                "Bạn sắp đổi Recovery Model sang SIMPLE.\n"
                "Thao tác này sẽ phá vỡ chuỗi LOG backup hiện tại.\n"
                "Tiếp tục?"
            ):
                return

        # Hỏi có muốn chỉ sinh script?
        generate_sql_only = messagebox.askyesno(
            "Tùy chọn",
            "Bạn có muốn CHỈ SINH SCRIPT T-SQL (không thực thi), để kiểm tra trước không?"
        )

        # Tạo script
        sqls = []
        for db in targets:
            sqls.append(f"ALTER DATABASE [{db}] SET RECOVERY {target_model};")

        # Hiển thị script
        self._clear_log()
        self._log("===== SCRIPT T-SQL =====")
        for s in sqls:
            self._log(s)
        self._log("========================")

        if generate_sql_only:
            messagebox.showinfo("Script đã sinh", "Đã sinh script trong khung log. Sao chép và chạy trên SSMS nếu cần.")
            return

        # Thực thi trong thread
        def worker():
            conn = self.owner.conn
            prev_autocommit = getattr(conn, "autocommit", False)
            try:
                conn.autocommit = True
                cur = conn.cursor()
                for s in sqls:
                    try:
                        cur.execute(s)
                        self._queue.put(("LOG", f"[OK] {s}"))
                    except Exception as ex:
                        self._queue.put(("LOG", f"[LỖI] {s}\n      → {ex}"))
                cur.close()
                # Tải lại danh sách sau khi đổi
                self._queue.put(("REFRESH", None))
            except Exception as e:
                self._queue.put(("LOG", f"[LỖI] Thực thi thất bại: {e}"))
            finally:
                try:
                    conn.autocommit = prev_autocommit
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()
        self.after(100, self._poll_queue_actions)

    def _poll_queue_actions(self):
        """Đọc hàng đợi sau khi thực thi thao tác đổi Recovery."""
        try:
            tag, payload = self._queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_queue_actions)
            return

        if tag == "LOG":
            self._log(str(payload))
            self.after(50, self._poll_queue_actions)
        elif tag == "REFRESH":
            self._reload_databases()
            messagebox.showinfo("Hoàn tất", "Đã thực thi xong. Danh sách sẽ được làm mới.")

