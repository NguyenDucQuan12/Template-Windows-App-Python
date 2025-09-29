import os
import re
import pyodbc
import threading
import customtkinter as ctk
from tkinter import ttk, messagebox
from datetime import datetime


from utils.modal_loading import ModalLoadingPopup

class RestoreFrame(ctk.CTkFrame):
    """
    Khung khôi phục SQL Server:
      - Đọc lịch sử backup từ msdb (FULL/DIFF/LOG)
      - Tính chain đến STOPAT
      - Tiền kiểm tra RecoveryForkID (normalize) + LSN chain (fallback)
      - Sinh script RESTORE (FULL -> DIFF -> LOG -> STOPAT/RECOVERY)
      - Thực thi bằng autocommit + Database=master (tránh lỗi 226)
    """

    # --- cấu hình chung ---
    DEFAULT_QUERY_TIMEOUT = 30   # giây: cho truy vấn msdb, RESTORE HEADERONLY
    DEFAULT_EXEC_TIMEOUT  = 0    # giây: 0 = không giới hạn, cho RESTORE dài
    LOG_TS_FORMAT         = "%H:%M:%S"

    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        # Popup loading
        self.loading = ModalLoadingPopup(parent)

        # state
        self.current_db = None
        self.timeline_rows = []  # list các bản ghi backupset đã nạp từ msdb

        # layout
        self.grid_rowconfigure(6, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Khôi phục dữ liệu (RESTORE)", font=ctk.CTkFont(size=16, weight="bold"))\
            .grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        # chọn DB
        top = ctk.CTkFrame(self)
        top.grid(row=1, column=0, padx=12, pady=6, sticky="ew")
        top.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(top, text="CSDL nguồn:").grid(row=0, column=0, padx=(4,6), pady=6, sticky="e")
        all_dbs = sorted(list(self.owner.selected_databases)) if hasattr(self.owner, "selected_databases") else []
        self.cbo_db = ctk.CTkComboBox(top, values=all_dbs, width=240, command=lambda _: self._on_change_db())
        self.cbo_db.grid(row=0, column=1, padx=(0,8), pady=6, sticky="w")
        if all_dbs:
            self.cbo_db.set(all_dbs[0])
        ctk.CTkButton(top, text="Tải lịch sử sao lưu", command=self.load_timeline).grid(row=0, column=2, padx=6, pady=6, sticky="w")

        # mục tiêu khôi phục
        target = ctk.CTkFrame(self)
        target.grid(row=2, column=0, padx=12, pady=6, sticky="ew")
        target.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(target, text="DB đích:").grid(row=0, column=0, padx=(4,6), pady=6, sticky="e")
        self.ent_target_db = ctk.CTkEntry(target, width=260, placeholder_text="Để trùng DB nguồn nếu muốn ghi đè")
        self.ent_target_db.grid(row=0, column=1, padx=(0,8), pady=6, sticky="w")

        self.var_overwrite = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(target, text="WITH REPLACE (ghi đè nếu cùng tên)", variable=self.var_overwrite)\
            .grid(row=0, column=2, padx=6, pady=6, sticky="w")

        self.var_relocate = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(target, text="MOVE file sang thư mục mới (khi restore sang DB mới)", variable=self.var_relocate)\
            .grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ctk.CTkLabel(target, text="Data (.mdf/.ndf):").grid(row=1, column=2, padx=(6,6), pady=6, sticky="e")
        self.ent_data_path = ctk.CTkEntry(target, width=240, placeholder_text=r"VD: D:\SQL_Data\\")
        self.ent_data_path.grid(row=1, column=3, padx=(0,6), pady=6, sticky="w")

        ctk.CTkLabel(target, text="Log (.ldf):").grid(row=2, column=2, padx=(6,6), pady=6, sticky="e")
        self.ent_log_path = ctk.CTkEntry(target, width=240, placeholder_text=r"VD: E:\SQL_Log\\")
        self.ent_log_path.grid(row=2, column=3, padx=(0,6), pady=6, sticky="w")

        # STOPAT
        stopat = ctk.CTkFrame(self)
        stopat.grid(row=3, column=0, padx=12, pady=6, sticky="ew")
        stopat.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(stopat, text="Thời điểm khôi phục (ISO 2025-09-18T08:06:00):").grid(row=0, column=0, padx=(4,6), pady=6, sticky="e")
        self.ent_stopat = ctk.CTkEntry(stopat, width=240, placeholder_text="VD: 2025-09-18T08:06:00 (để trống = mới nhất)")
        self.ent_stopat.grid(row=0, column=1, padx=(0, 6), pady=6, sticky="w")
        ctk.CTkButton(stopat, text="Kiểm tra STOPAT", command=self.check_stopat).grid(row=0, column=2, padx=6, pady=6, sticky="w")

        # Timeline
        self.tree = ttk.Treeview(self, columns=("kind","start","finish","copy_only","media_set_id"), show="headings", height=12)
        self.tree.heading("kind", text="LOẠI")
        self.tree.heading("start", text="START")
        self.tree.heading("finish", text="FINISH")
        self.tree.heading("copy_only", text="COPY_ONLY")
        self.tree.heading("media_set_id", text="MEDIA SET")
        self.tree.column("kind", width=70, anchor="w")
        self.tree.column("start", width=170, anchor="w")
        self.tree.column("finish", width=170, anchor="w")
        self.tree.column("copy_only", width=90, anchor="w")
        self.tree.column("media_set_id", width=100, anchor="w")
        self.tree.grid(row=4, column=0, padx=12, pady=(0, 8), sticky="nsew")

        vsb = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        vsb.grid(row=4, column=1, sticky="ns", pady=(0,8))

        # Hành động
        actions = ctk.CTkFrame(self)
        actions.grid(row=5, column=0, padx=12, pady=6, sticky="ew")
        ctk.CTkButton(actions, text="🧩 Sinh script (SSMS)", command=lambda: self._do_restore(generate_only=True))\
            .grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ctk.CTkButton(actions, text="⚙️ Chạy luôn", command=lambda: self._do_restore(generate_only=False))\
            .grid(row=0, column=1, padx=6, pady=6, sticky="w")

        # Status
        self.status = ctk.CTkTextbox(self, height=150)
        self.status.grid(row=6, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self._info("Chọn DB, nạp mốc từ msdb, nhập STOPAT hoặc chọn mốc trong bảng (chọn log/diff làm gợi ý).")

        # init
        if all_dbs:
            self._on_change_db()

    # ------------------------ Log helpers ------------------------

    def _log(self, s: str):
        self.status.configure(state="normal")
        self.status.insert("end", s + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def _log_line(self, level: str, msg: str):
        ts = datetime.now().strftime(self.LOG_TS_FORMAT)
        prefix = {"INFO":"ℹ️","WARN":"⚠️","ERR":"✗","OK":"✓","DBG":"·"}.get(level.upper(), "·")
        self._log(f"[{ts}] {prefix} {msg}")

    def _info(self, msg): self._log_line("INFO", msg)
    def _warn(self, msg): self._log_line("WARN", msg)
    def _err(self, msg):  self._log_line("ERR",  msg)
    def _ok(self, msg):   self._log_line("OK",   msg)
    def _dbg(self, msg):  self._log_line("DBG",  msg)

    def _clear_log(self):
        self.status.configure(state="normal")
        self.status.delete("1.0", "end")
        self.status.configure(state="disabled")

    # ------------------------ UI events ------------------------

    def _on_change_db(self):
        self.current_db = self.cbo_db.get().strip() or None
        if self.current_db:
            self.ent_target_db.delete(0, "end")
            self.ent_target_db.insert(0, self.current_db)
            self.load_timeline()

    # ------------------------ Data (msdb) ------------------------

    def load_timeline(self):
        """Truy vấn msdb dựng timeline FULL/DIFF/LOG (cho DB hiện tại)."""
        # Xóa danh sách cũ trong treeview
        self._clear_timeline()
        # Lấy DB hiện tại
        db = self.current_db
        if not db:
            messagebox.showwarning("Chưa chọn DB", "Hãy chọn CSDL nguồn."); return
        if not self.owner.connection_string:
            messagebox.showwarning("Chưa kết nối", "Chưa có kết nối SQL Server."); return

        try:
            # kết nối tới CSDL
            self.conn = self.owner._connect()
            # Nếu chưa kết nối thì không làm gì cả
            if not self.conn:
                return
            
            self.conn.timeout = self.DEFAULT_QUERY_TIMEOUT
            
            # Tạo con trỏ
            with self.conn.cursor() as cursor:
                # Thực hiện truy vấn
                sql = r"""
                    SELECT
                        bs.backup_set_id,
                        bs.media_set_id,
                        bs.database_name,
                        bs.type,                -- D=Full, I=Diff, L=Log
                        bs.is_copy_only,
                        CONVERT(nvarchar(23), bs.backup_start_date, 121) as start_121,
                        CONVERT(nvarchar(23), bs.backup_finish_date, 121) as finish_121,
                        bs.first_lsn, bs.last_lsn, bs.differential_base_lsn
                    FROM msdb.dbo.backupset bs
                    WHERE bs.database_name = ?
                    ORDER BY bs.backup_finish_date ASC
                """
                cursor.execute(sql, (db,))
                self.timeline_rows = cursor.fetchall()
        except Exception:
            pass
        finally:
            self.conn.close()

        # Hiển thị
        for r in self.timeline_rows:
            k = {"D": "FULL", "I": "DIFF", "L": "LOG"}.get(r.type, r.type)
            self.tree.insert("", "end", values=(k, r.start_121, r.finish_121, str(r.is_copy_only), str(r.media_set_id)))

        self._ok(f"Nạp mốc cho [{db}] xong ({len(self.timeline_rows)} bản backup).")

    def _clear_timeline(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.timeline_rows = []

    # -------------------- STOPAT & Kiểm tra --------------------

    def _parse_stopat(self):
        s = self.ent_stopat.get().strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            messagebox.showwarning("STOPAT không hợp lệ", "Hãy dùng ISO: 2025-09-18T08:06:00")
            return None

    def check_stopat(self):
        db = self.current_db
        if not db:
            messagebox.showwarning("Chưa chọn DB", "Chọn DB trước."); return
        if not self.timeline_rows:
            messagebox.showwarning("Chưa có timeline", "Nhấn 'Tải lịch sử sao lưu' trước."); return
        stopat = self._parse_stopat()
        ok, info = self._compute_restore_chain(stopat)
        self._clear_log()
        if ok:
            self._ok("STOPAT hợp lệ. Chuỗi khôi phục xác định:")
            for line in info["summary"]:
                self._log("  " + line)
        else:
            self._err("STOPAT KHÔNG khả dụng: " + info)

    # -------------------- Tính chuỗi khôi phục --------------------

    def _compute_restore_chain(self, stopat):
        """
        Trả:
          (True, {"base": base_row, "diff": diff_row or None, "logs": [rows...], "summary":[...], "final_contains_stopat": bool})
        hoặc (False, "lí do")
        """
        rows = self.timeline_rows
        if not rows:
            return False, "Không có lịch sử backup trong msdb."

        stop_dt = stopat or datetime(9999,12,31,0,0,0)

        # 1) FULL non-copy_only trước/bằng STOPAT
        fulls = [r for r in rows if r.type == 'D' and not r.is_copy_only and datetime.fromisoformat(r.finish_121) <= stop_dt]
        if not fulls:
            return False, "Không tìm thấy FULL (non COPY_ONLY) trước/bằng STOPAT."
        base = sorted(fulls, key=lambda r: datetime.fromisoformat(r.finish_121))[-1]

        # 2) DIFF khớp base (nếu có)
        diffs = [
            r for r in rows
            if r.type == 'I'
            and datetime.fromisoformat(r.finish_121) <= stop_dt
            and datetime.fromisoformat(r.start_121) > datetime.fromisoformat(base.start_121)
            and r.differential_base_lsn == base.first_lsn
        ]
        diff = sorted(diffs, key=lambda r: datetime.fromisoformat(r.finish_121))[-1] if diffs else None

        # 3) LOGs nối tiếp
        start_lsn = diff.last_lsn if diff else base.last_lsn
        logs_all = [r for r in rows if r.type == 'L' and r.last_lsn > start_lsn]
        logs_before = [r for r in logs_all if datetime.fromisoformat(r.finish_121) < stop_dt]

        same_day = lambda d: d.date() == stop_dt.date()
        logs_cover = [
            r for r in logs_all
            if datetime.fromisoformat(r.finish_121) >= stop_dt
            and same_day(datetime.fromisoformat(r.start_121))
            and same_day(datetime.fromisoformat(r.finish_121))
        ]
        final_log = logs_cover[0] if logs_cover else None

        chosen_logs = logs_before[:]
        final_contains_stopat = False
        if final_log:
            chosen_logs.append(final_log)
            final_contains_stopat = True

        # summary
        summ = []
        summ.append(f"FULL:   finish={base.finish_121} (media_set={base.media_set_id})")
        summ.append(f"DIFF:   {(diff.finish_121 if diff else '(none)')} (media_set={diff.media_set_id if diff else 'n/a'})")
        summ.append(f"LOGS:   {len(chosen_logs)} bản; " + ("có bản bao trùm STOPAT" if final_contains_stopat else "không bản bao trùm STOPAT"))

        return True, {
            "base": base, "diff": diff, "logs": chosen_logs,
            "summary": summ, "final_contains_stopat": final_contains_stopat
        }

    # -------------------- Helper: msdb.media to file list --------------------

    def _media_to_files(self, media_set_id):
        try:
            # kết nối tới CSDL
            self.conn = self.owner._connect()
            # Nếu chưa kết nối thì không làm gì cả
            if not self.conn:
                return
            
            self.conn.timeout = self.DEFAULT_QUERY_TIMEOUT
            
            # Tạo con trỏ
            with self.conn.cursor() as cursor:
                # Thực hiện truy vấn
                sql = """
                    SELECT physical_device_name, family_sequence_number
                    FROM msdb.dbo.backupmediafamily
                    WHERE media_set_id = ?
                    ORDER BY family_sequence_number
                """
                cursor.execute(sql, (media_set_id,))
                return cursor.fetchall()
        except:
            pass
        finally:
            self.conn.close()

    def _from_disk_clause(self, media_set_id, missing_files):
        """
        Trả chuỗi: "DISK = N'...'" , "DISK = N'...'"
        - Kiểm tra os.path.exists cho đường dẫn cục bộ/UNC
        - Bỏ qua URL (không hỗ trợ trong bản này theo yêu cầu)
        """
        rows = self._media_to_files(media_set_id)
        parts = []
        for r in rows:
            p = r.physical_device_name
            p_str = p if isinstance(p, str) else str(p)
            esc = p_str.replace("'", "''")
            parts.append(f"DISK = N'{esc}'")

            # local drive hoặc UNC
            if re.match(r"^[a-zA-Z]:\\", p_str) or p_str.startswith("\\\\"):
                if not os.path.exists(p_str):
                    missing_files.append(p_str)

        return ", ".join(parts)

    # -------------------- HEADERONLY & Preflight chain --------------------

    def _norm_guid(self, g):
        if g is None:
            return None
        s = str(g).strip().lower().replace("{","").replace("}","").replace("-", "")
        return s or None

    def _extract_header_info(self, media_set_id):
        """
        Gọi RESTORE HEADERONLY để lấy:
          RecoveryForkID, FirstLSN, LastLSN, DatabaseBackupLSN, BackupStart/FinishDate
        """
        missing = []
        clause = self._from_disk_clause(media_set_id, missing_files=missing)  # vẫn generate DISK list, kể cả thiếu file
        # Cảnh báo nhưng vẫn thử HEADERONLY (vì SQL Server đọc ở server side)
        if missing:
            self._warn(f"Thiếu file (client không thấy): {len(missing)} tệp. HEADERONLY vẫn thử trên server.")

        # Mượn/chuẩn bị kết nối autocommit+master
        base_conn = self.owner._connect()
        if not base_conn:
            return
        
        conn_str = getattr(self.owner, "connection_string", None)
        if conn_str:
            cs = re.sub(r"(;|\A)\s*Database\s*=\s*[^;]*", "", conn_str, flags=re.I)
            if not cs.endswith(";"):
                cs += ";"
            cs += "Database=master;"
            cnx = pyodbc.connect(cs, autocommit=True)
        else:
            base_conn.autocommit = True
            cnx = base_conn
        
        try:
            cnx.timeout = self.DEFAULT_QUERY_TIMEOUT
        except Exception:
            pass

        cur = cnx.cursor()

        sql = f"RESTORE HEADERONLY FROM {clause}"
        cur.execute(sql)
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"HEADERONLY không trả dữ liệu (media_set_id={media_set_id}).")

        # Map theo tên cột động
        cols = [d[0] for d in cur.description]
        data = dict(zip(cols, row))

        def pick(*names):
            for n in names:
                if n in data: return data[n]
            return None

        info = {
            "RecoveryForkID":   self._norm_guid(pick("RecoveryForkID","RecoveryForkId","RecoveryForkGUID")),
            "FirstLSN":         pick("FirstLSN"),
            "LastLSN":          pick("LastLSN"),
            "DatabaseBackupLSN":pick("DatabaseBackupLSN"),
            "BackupStartDate":  pick("BackupStartDate"),
            "BackupFinishDate": pick("BackupFinishDate"),
        }
        # xả resultsets nếu có
        while cur.nextset():
            pass
        if cnx is not base_conn:
            cnx.close()
        if base_conn:
            base_conn.close()
        return info

    def _preflight_validate_chain(self, base_row, diff_row, log_rows):
        """
        Xác nhận fork & LSN chain trước khi chạy:
          - Nếu cả hai vế đều có fork → so sánh fork.
          - Nếu một bên thiếu fork → fallback so LSN.
          - Với mỗi LOG: yêu cầu FirstLSN <= currentLSN < LastLSN.
        """
        # FULL
        h_full = self._extract_header_info(base_row.media_set_id)
        fork = h_full["RecoveryForkID"]
        current = h_full["LastLSN"]

        # DIFF
        h_diff = None
        if diff_row:
            h_diff = self._extract_header_info(diff_row.media_set_id)
            if fork and h_diff["RecoveryForkID"] and h_diff["RecoveryForkID"] != fork:
                return (False, f"DIFF media_set={diff_row.media_set_id} khác fork với FULL "
                               f"({h_diff['RecoveryForkID']} ≠ {fork}).")
            current = h_diff["LastLSN"] or current

        # LOG chain
        checked = 0
        for r in log_rows:
            h_log = self._extract_header_info(r.media_set_id)

            # So fork nếu cả 2 có
            if fork and h_log["RecoveryForkID"] and h_log["RecoveryForkID"] != fork:
                return (False, f"LOG media_set={r.media_set_id} khác fork với FULL/DIFF "
                               f"({h_log['RecoveryForkID']} ≠ {fork}).")

            flsn = h_log["FirstLSN"]; llsn = h_log["LastLSN"]
            if flsn is None or llsn is None:
                return (False, f"LOG media_set={r.media_set_id} thiếu First/Last LSN (HEADERONLY).")

            def to_int(x):
                try: return int(x)
                except: return None

            c = to_int(current); f = to_int(flsn); l = to_int(llsn)
            if None not in (c,f,l):
                if not (f <= c < l):
                    return (False, f"LOG media_set={r.media_set_id} không nối được LSN "
                                   f"(FirstLSN={flsn}, LastLSN={llsn}, currentLSN={current}).")
            else:
                # fallback so sánh chuỗi
                if not (str(flsn) <= str(current) < str(llsn)):
                    return (False, f"LOG media_set={r.media_set_id} không nối được LSN "
                                   f"(FirstLSN={flsn}, LastLSN={llsn}, currentLSN={current}).")

            current = llsn
            checked += 1

        info = {
            "full_fork": fork or "(unknown/null)",
            "full_last_lsn": h_full["LastLSN"],
            "diff_last_lsn": (h_diff or {}).get("LastLSN"),
            "logs_checked": checked,
            "end_lsn": current,
        }
        return (True, info)

    # -------------------- Sinh script RESTORE & Thực thi --------------------

    def _do_restore(self, generate_only: bool):
        """Sinh script (và chạy nếu generate_only=False) với preflight kiểm tra an toàn."""
        db = self.current_db
        if not db:
            messagebox.showwarning("Chưa chọn DB", "Chọn DB nguồn trước."); return
        if not self.owner.connection_string:
            messagebox.showwarning("Chưa kết nối", "Chưa có kết nối SQL Server."); return
        if not self.timeline_rows:
            messagebox.showwarning("Chưa có timeline", "Nhấn 'Tải lịch sử sao lưu' trước."); return

        stopat = self._parse_stopat()
        ok, info = self._compute_restore_chain(stopat)
        if not ok:
            self._clear_log()
            self._err("STOPAT không khả dụng: " + info)
            return

        # Input người dùng
        target_db = self.ent_target_db.get().strip() or db
        overwrite = self.var_overwrite.get()
        relocate  = self.var_relocate.get()
        data_path = (self.ent_data_path.get().strip() or "")
        log_path  = (self.ent_log_path.get().strip()  or "")

        # FROM DISK
        missing = []
        from_base = self._from_disk_clause(info["base"].media_set_id, missing)
        from_diff = None
        if info["diff"]:
            from_diff = self._from_disk_clause(info["diff"].media_set_id, missing)
        from_logs = []
        for r in info["logs"]:
            from_logs.append(self._from_disk_clause(r.media_set_id, missing))

        if missing:
            self._warn("Thiếu các tệp backup (client không thấy). Nếu đường dẫn là của SQL Server thì vẫn có thể chạy ok:")
            for p in missing:
                self._log("  - " + p)

        # MOVE clause (khi restore sang DB mới + relocate)
        move_clause = ""
        if target_db != db and relocate:
            try:
                # kết nối tới CSDL
                self.conn = self.owner._connect()
                # Nếu chưa kết nối thì không làm gì cả
                if not self.conn:
                    return
                
                self.conn.timeout = self.DEFAULT_QUERY_TIMEOUT
                
                # Tạo con trỏ
                with self.conn.cursor() as cursor:
                    # Thực hiện truy vấn
                    cursor.execute("""
                        SELECT logical_name, file_type, file_number, physical_name
                        FROM msdb.dbo.backupfile bf
                        WHERE bf.backup_set_id = ?
                        ORDER BY file_type, file_number
                    """, (info["base"].backup_set_id,))
                    rows = cursor.fetchall()
            except:
                pass
            finally:
                self.conn.close()

            parts = []
            data_idx = 1
            log_idx  = 1
            for r in rows:
                l = r.logical_name.replace("'", "''")
                if r.file_type == 'L':
                    basep = os.path.join(log_path, f"{target_db}_log" + ("" if log_idx==1 else f"_{log_idx}"))
                    parts.append(f"MOVE N'{l}' TO N'{basep}.ldf'")
                    log_idx += 1
                else:
                    basep = os.path.join(data_path, f"{target_db}" + ("" if data_idx==1 else f"_{data_idx}"))
                    ext = ".mdf" if data_idx == 1 else ".ndf"
                    parts.append(f"MOVE N'{l}' TO N'{basep}{ext}'")
                    data_idx += 1
            if parts:
                move_clause = ", " + ", ".join(parts)

        # Preflight kiểm tra fork/LSN chain (an toàn)
        pv_ok, pv_info = self._preflight_validate_chain(info["base"], info["diff"], info["logs"])
        self._info("— SUMMARY —")
        for line in info["summary"]:
            self._log("  " + line)
        if pv_ok:
            self._ok(f"Preflight OK: fork={pv_info['full_fork']}, logs_checked={pv_info['logs_checked']}")
        else:
            self._err("Preflight FAIL: " + pv_info)
            messagebox.showerror("Chuỗi backup không hợp lệ", pv_info)
            return

        # Sinh script
        qTarget = f"[{target_db}]"
        use_checksum = True
        stats_n = 5

        sql_lines = []
        sql_lines.append("SET NOCOUNT ON;")
        sql_lines.append("USE master;")
        sql_lines.append("")
        if target_db == db:
            esc_target = target_db.replace("'", "''")
            sql_lines += [
                f"-- Ensure SINGLE_USER on [{esc_target}] for overwrite",
                f"IF DB_ID(N'{esc_target}') IS NOT NULL",
                "BEGIN",
                f"  ALTER DATABASE {qTarget} SET SINGLE_USER WITH ROLLBACK IMMEDIATE;",
                "END",
                ""
            ]

        # FULL
        opts = []
        if use_checksum: opts.append("CHECKSUM")
        opts.append(f"STATS = {stats_n}")
        if overwrite:    opts.append("REPLACE")
        opts.append("NORECOVERY")
        opts_str = ", ".join(opts)
        sql_lines.append("-- RESTORE FULL")
        sql_lines.append(f"RESTORE DATABASE {qTarget} FROM {from_base}")
        sql_lines.append(f"WITH {opts_str}{move_clause};\n")

        # DIFF
        if from_diff:
            sql_lines.append("-- RESTORE DIFF")
            sql_lines.append(f"RESTORE DATABASE {qTarget} FROM {from_diff}")
            sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, NORECOVERY;\n")

        # LOGs
        if info["logs"]:
            last_idx = len(info["logs"]) - 1
            final_contains = info["final_contains_stopat"]
            for i, r in enumerate(info["logs"]):
                fd = from_logs[i]
                final = (i == last_idx)
                if final and final_contains and stopat is not None:
                    sql_lines.append("-- RESTORE LOG (final, STOPAT)")
                    sql_lines.append(f"RESTORE LOG {qTarget} FROM {fd}")
                    sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, STOPAT = '{stopat.isoformat(sep=' ')}', RECOVERY;\n")
                elif final and not final_contains:
                    sql_lines.append("-- RESTORE LOG (final)")
                    sql_lines.append(f"RESTORE LOG {qTarget} FROM {fd}")
                    sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, RECOVERY;\n")
                else:
                    sql_lines.append("-- RESTORE LOG")
                    sql_lines.append(f"RESTORE LOG {qTarget} FROM {fd}")
                    sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, NORECOVERY;\n")
        else:
            sql_lines.append("-- No LOGs selected -> RECOVERY at FULL/DIFF")
            sql_lines.append(f"RESTORE DATABASE {qTarget} WITH RECOVERY;\n")

        if target_db == db:
            sql_lines += [
                f"-- Back to MULTI_USER on [{target_db}]",
                f"ALTER DATABASE {qTarget} SET MULTI_USER;"
            ]

        full_sql = "\n".join(sql_lines)

        # Hiển thị hoặc thực thi
        self._info("— SCRIPT —")
        self._log(full_sql)

        if generate_only:
            messagebox.showinfo("Script sẵn sàng", "Script đã hiển thị trong ô trạng thái.\nCopy và dán vào SSMS để chạy.")
            return

        # Thực thi (autocommit + master)
        self.loading.show()
        threading.Thread(target= self.run_backup_in_thread, args=(full_sql, target_db), daemon=True).start()

    def run_backup_in_thread(self, sql_query, target_db):
        """
        Thực thi câu lệnh backup trong 1 luồng riêng
        """
        try:
            # Kết nối đến DB
            base_conn = self.owner._connect()
            if not base_conn:
                # Ẩn popup
                self.loading.schedule_hide()
                self.after(0, lambda:messagebox.showwarning("Chưa kết nối", "Chưa có kết nối SQL Server."))
                return

            conn_str = getattr(self.owner, "connection_string", None)
            if conn_str:
                cs = re.sub(r"(;|\A)\s*Database\s*=\s*[^;]*", "", conn_str, flags=re.I)
                if not cs.endswith(";"):
                    cs += ";"
                cs += "Database=master;"
                restore_cnx = pyodbc.connect(cs, autocommit=True, timeout=self.DEFAULT_EXEC_TIMEOUT)
            else:
                base_conn.autocommit = True
                restore_cnx = base_conn

            try:
                restore_cnx.timeout = self.DEFAULT_EXEC_TIMEOUT
            except Exception:
                pass
            cur = restore_cnx.cursor()
            cur.execute(sql_query)

            # Xả hết result-sets để batch chạy trọn vẹn
            while True:
                try:
                    _ = cur.fetchall() if cur.description else None
                except pyodbc.ProgrammingError:
                    pass
                if not cur.nextset():
                    break

            # Kiểm chứng trạng thái
            vcur = restore_cnx.cursor()

            vcur.execute("SELECT state_desc, recovery_model_desc, user_access_desc FROM sys.databases WHERE name = ?", (target_db,))
            row = vcur.fetchone()
            if row:
                self.after(0, lambda:self._ok(f"[{target_db}] state={row.state_desc}, recovery={row.recovery_model_desc}, access={row.user_access_desc}"))

            if restore_cnx is not base_conn:
                restore_cnx.close()

            if base_conn:
                base_conn.close()

            self.loading.schedule_hide()
            self.after(0, lambda:messagebox.showinfo("Khôi phục thành công", f"CSDL {target_db} đã được khôi phục về thời gian chỉ định"))

        except pyodbc.Error as e:
            # Lấy thông tin lỗi sâu
            err_str = str(e)

            self.after(0, lambda err = e:self._err(f"Lỗi ODBC/SQL: {err}"))
            if "4330" in err_str:
                self.after(0, lambda:self._err("Mã 4330: Recovery path không khớp (fork/LSN). Hãy xem phần SUMMARY & Preflight."))
            elif "226" in err_str:
                self.after(0, lambda:self._err("Mã 226: ALTER DATABASE không được phép trong multi-statement transaction. Hãy đảm bảo autocommit + Database=master (đã áp dụng)."))

            self.loading.schedule_hide()
            self.after(0, lambda err =e:messagebox.showerror("Lỗi khôi phục", err))
            return

        except Exception as e:
            self.loading.schedule_hide()
            self.after(0, lambda err = e:self._err(f"Lỗi không xác định: {err}"))
            self.after(0, lambda err = e: messagebox.showerror("Lỗi khôi phục", err))
            return