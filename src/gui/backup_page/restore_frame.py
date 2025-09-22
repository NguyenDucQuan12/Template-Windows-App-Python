import os
import re
import customtkinter as ctk
from tkinter import ttk, messagebox
from datetime import datetime

class RestoreFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        # state
        self.current_db = None
        self.timeline_rows = []  # lưu các bản backup trong msdb (đã truy vấn)
        # cấu hình UI
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
        ctk.CTkButton(top, text="↻ Nạp mốc (msdb)", command=self.load_timeline).grid(row=0, column=2, padx=6, pady=6, sticky="w")

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

        ctk.CTkLabel(stopat, text="Thời điểm khôi phục (ISO):").grid(row=0, column=0, padx=(4,6), pady=6, sticky="e")
        self.ent_stopat = ctk.CTkEntry(stopat, width=240, placeholder_text="VD: 2025-09-18T08:06:00 (để trống = mới nhất)")
        self.ent_stopat.grid(row=0, column=1, padx=(0, 6), pady=6, sticky="w")
        ctk.CTkButton(stopat, text="Kiểm tra STOPAT", command=self.check_stopat).grid(row=0, column=2, padx=6, pady=6, sticky="w")

        # Timeline (FULL/DIFF/LOG) từ msdb
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
        self._log("• Chọn DB, nạp mốc từ msdb, nhập STOPAT hoặc chọn mốc trong bảng (chọn log/diff làm gợi ý).")

        # init
        if all_dbs:
            self._on_change_db()

    # ------------------------ Utils UI ------------------------

    def _log(self, s: str):
        self.status.configure(state="normal")
        self.status.insert("end", s + "\n")
        self.status.see("end")
        self.status.configure(state="disabled")

    def _clear_log(self):
        self.status.configure(state="normal")
        self.status.delete("1.0", "end")
        self.status.configure(state="disabled")

    def _on_change_db(self):
        self.current_db = self.cbo_db.get().strip() or None
        if self.current_db:
            self.ent_target_db.delete(0, "end")
            self.ent_target_db.insert(0, self.current_db)
            self.load_timeline()

    # ------------------------ Data (msdb) ------------------------

    def load_timeline(self):
        """Truy vấn msdb dựng timeline FULL/DIFF/LOG (cho DB hiện tại)."""
        self._clear_timeline()
        db = self.current_db
        if not db:
            messagebox.showwarning("Chưa chọn DB", "Hãy chọn CSDL nguồn."); return
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Chưa có kết nối SQL Server."); return
        cur = self.owner.conn.cursor()
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
        cur.execute(sql, (db,))
        self.timeline_rows = cur.fetchall()

        # hiển thị
        for r in self.timeline_rows:
            k = {"D": "FULL", "I": "DIFF", "L": "LOG"}.get(r.type, r.type)
            self.tree.insert("", "end", values=(k, r.start_121, r.finish_121, str(r.is_copy_only), str(r.media_set_id)))

        self._log(f"• Nạp mốc cho [{db}] xong ({len(self.timeline_rows)} bản backup).")

    def _clear_timeline(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.timeline_rows = []

    # -------------------- STOPAT & Kiểm tra --------------------

    def _parse_stopat(self):
        """Đọc STOPAT từ ô; nếu trống -> None (mới nhất)."""
        s = self.ent_stopat.get().strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s)
        except Exception:
            messagebox.showwarning("STOPAT không hợp lệ", "Hãy dùng ISO: 2025-09-18T08:06:00")
            return None

    def check_stopat(self):
        """Kiểm tra logic khôi phục có thể thực hiện tới STOPAT không (dựa vào msdb)."""
        db = self.current_db
        if not db:
            messagebox.showwarning("Chưa chọn DB", "Chọn DB trước."); return
        if not self.timeline_rows:
            messagebox.showwarning("Chưa có timeline", "Nhấn 'Nạp mốc (msdb)' trước."); return
        stopat = self._parse_stopat()
        # Nếu None -> hiểu là mới nhất; vẫn tính chain tới cuối
        ok, info = self._compute_restore_chain(stopat)
        self._clear_log()
        if ok:
            self._log("✓ STOPAT hợp lệ. Chuỗi khôi phục xác định:")
            for line in info["summary"]:
                self._log("  " + line)
        else:
            self._log("✗ STOPAT KHÔNG khả dụng: " + info)

    # -------------------- Tính chuỗi khôi phục --------------------

    def _compute_restore_chain(self, stopat):
        """
        Tính chuỗi (FULL non copy_only <= stopat) → (DIFF gần nhất) → LOGs nối tiếp tới/bao trùm stopat.
        Trả:
          (True, {"base": base_row, "diff": diff_row or None, "logs": [rows...], "summary":[...], "final_contains_stopat": True/False})
        hoặc (False, "lí do").
        """
        rows = self.timeline_rows
        if not rows:
            return False, "Không có lịch sử backup trong msdb."

        # Nếu không có STOPAT -> đặt 9999-12-31 để lấy mới nhất
        stop_dt = stopat or datetime(9999,12,31,0,0,0)

        # 1) FULL non-copy_only trước/bằng STOPAT
        fulls = [r for r in rows if r.type == 'D' and not r.is_copy_only and datetime.fromisoformat(r.finish_121) <= stop_dt]
        if not fulls:
            return False, "Không tìm thấy FULL (non COPY_ONLY) trước/bằng STOPAT."
        base = sorted(fulls, key=lambda r: datetime.fromisoformat(r.finish_121))[-1]

        # 2) DIFF khớp base trước/bằng STOPAT, thỏa điều kiện msdb
        diffs = [
            r for r in rows
            if r.type == 'I'
            and datetime.fromisoformat(r.finish_121) <= stop_dt
            and datetime.fromisoformat(r.start_121) > datetime.fromisoformat(base.start_121)
            and r.differential_base_lsn == base.first_lsn
        ]
        diff = sorted(diffs, key=lambda r: datetime.fromisoformat(r.finish_121))[-1] if diffs else None

        # 3) LOGs sau DIFF (nếu có) hoặc sau FULL
        start_lsn = diff.last_lsn if diff else base.last_lsn
        logs_all = [r for r in rows if r.type == 'L' and r.last_lsn > start_lsn]
        logs_before = [r for r in logs_all if datetime.fromisoformat(r.finish_121) < stop_dt]
        # log bao trùm STOPAT (cùng ngày): log có finish >= stopat (dùng để STOPAT chính xác)
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
            # có log bao trùm STOPAT -> thêm nó là cuối, STOPAT dùng STOPAT=...
            chosen_logs.append(final_log)
            final_contains_stopat = True
        # Nếu không có log cover: khôi phục đến log cuối trước STOPAT (RECOVERY không STOPAT)
        # hoặc nếu không có log nào: khôi phục tại DIFF / FULL

        # Tạo tóm tắt
        summ = []
        summ.append(f"FULL:   finish={base.finish_121} (media_set={base.media_set_id})")
        summ.append(f"DIFF:   {(diff.finish_121 if diff else '(none)')}")
        summ.append(f"LOGS:   {len(chosen_logs)} bản; " + ("có bản bao trùm STOPAT" if final_contains_stopat else "không bản bao trùm STOPAT"))

        return True, {
            "base": base, "diff": diff, "logs": chosen_logs,
            "summary": summ, "final_contains_stopat": final_contains_stopat
        }

    # -------------------- Sinh FROM DISK + kiểm tra file --------------------

    def _media_to_files(self, media_set_id):
        """Trích danh sách file vật lý từ media_set_id (msdb.backupmediafamily)."""
        cur = self.owner.conn.cursor()
        sql = """
SELECT physical_device_name, family_sequence_number
FROM msdb.dbo.backupmediafamily
WHERE media_set_id = ?
ORDER BY family_sequence_number
"""
        cur.execute(sql, (media_set_id,))
        return cur.fetchall()

    def _from_disk_clause(self, media_set_id, missing_files):
        """
        Tạo chuỗi 'DISK = N'...' , DISK = N'...' ' và kiểm tra os.path.exists cho đường dẫn cục bộ.
        - Nếu đường dẫn dạng UNC \\server\\share\\... vẫn có thể exists nếu share mounted.
        - Nếu dạng URL (http, https, azure blob), bỏ qua kiểm tra tồn tại tại client.
        Ghi tên file không tồn tại vào missing_files (list).
        """
        rows = self._media_to_files(media_set_id)
        parts = []
        for r in rows:
            p = r.physical_device_name
            p_str = p if isinstance(p, str) else str(p)
            # tránh vấn đề escaping/format trong f-string: xây chuỗi an toàn bằng format
            esc = p_str.replace("'", "''")
            parts.append("DISK = N'{}'".format(esc))
            if re.match(r"^[a-zA-Z]:\\", p) or p.startswith("\\\\"):
                if not os.path.exists(p):
                    missing_files.append(p)
            else:
                # URL hoặc thiết bị đặc biệt: không kiểm tra tại client
                pass
        return ", ".join(parts)

    # -------------------- Sinh script RESTORE & Thực thi --------------------

    def _do_restore(self, generate_only: bool):
        """
        Sinh script dựa trên STOPAT + lựa chọn; nếu generate_only=False -> chạy luôn.
        Trước khi chạy: kiểm tra tồn tại mọi file backup.
        """
        db = self.current_db
        if not db:
            messagebox.showwarning("Chưa chọn DB", "Chọn DB nguồn trước."); return
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Chưa có kết nối SQL Server."); return
        if not self.timeline_rows:
            messagebox.showwarning("Chưa có timeline", "Nhấn 'Nạp mốc (msdb)' trước."); return

        stopat = self._parse_stopat()
        ok, info = self._compute_restore_chain(stopat)
        if not ok:
            self._clear_log()
            self._log("✗ STOPAT không khả dụng: " + info)
            return

        # chuẩn bị tham số
        target_db = self.ent_target_db.get().strip() or db
        overwrite = self.var_overwrite.get()
        relocate = self.var_relocate.get()
        data_path = (self.ent_data_path.get().strip() or "")
        log_path  = (self.ent_log_path.get().strip()  or "")
        tail_file = None  # TODO: nếu bạn muốn thêm Entry tail log, gán tại đây

        # Lấy clause FROM DISK cho FULL, DIFF, LOG và kiểm tra file
        missing = []
        from_base = self._from_disk_clause(info["base"].media_set_id, missing)
        from_diff = None
        if info["diff"]:
            from_diff = self._from_disk_clause(info["diff"].media_set_id, missing)
        from_logs = []
        for r in info["logs"]:
            from_logs.append(self._from_disk_clause(r.media_set_id, missing))

        if missing:
            self._clear_log()
            self._log("✗ Thiếu các tệp backup (không tìm thấy ở client; nếu chạy trên SQL Server vẫn có thể OK nếu đường dẫn hợp lệ tại máy chủ):")
            for p in missing:
                self._log("  - " + p)
            messagebox.showwarning("Thiếu tệp backup", "Có tệp không tìm thấy. Kiểm tra ô trạng thái.")
            return

        # Sinh MOVE clause nếu restore sang DB mới + relocate
        move_clause = ""
        if target_db != db and relocate:
            # Lấy danh sách logical_name từ msdb.backupfile của base
            cur = self.owner.conn.cursor()
            cur.execute("""
                SELECT logical_name, file_type, file_number, physical_name
                FROM msdb.dbo.backupfile bf
                WHERE bf.backup_set_id = ?
                ORDER BY file_type, file_number
                """, (info["base"].backup_set_id,))
            rows = cur.fetchall()
            # Dựng MOVE: data -> data_path, log -> log_path
            parts = []
            # tạo tên gợi ý: <TargetDb>[_n].mdf/ndf ; <TargetDb>_log[_n].ldf
            data_idx = 1
            log_idx  = 1
            for r in rows:
                l = r.logical_name.replace("'", "''")
                if r.file_type == 'L':
                    base = os.path.join(log_path, f"{target_db}_log" + ("" if log_idx==1 else f"_{log_idx}"))
                    parts.append(f"MOVE N'{l}' TO N'{base}.ldf'")
                    log_idx += 1
                else:
                    base = os.path.join(data_path, f"{target_db}" + ("" if data_idx==1 else f"_{data_idx}"))
                    # đuôi .mdf cho file đầu, .ndf cho các file sau
                    ext = ".mdf" if data_idx == 1 else ".ndf"
                    parts.append(f"MOVE N'{l}' TO N'{base}{ext}'")
                    data_idx += 1
            if parts:
                move_clause = ", " + ", ".join(parts)

        # Tạo script tương tự template bạn đưa, giản lược vừa đủ (FULL->DIFF->LOGs)
        qTarget = f"[{target_db}]"
        use_checksum = True
        stats_n = 5

        sql_lines = []
        sql_lines.append("SET NOCOUNT ON;")
        # Exclusive (SINGLE_USER) khi ghi đè đích trùng nguồn
        if target_db == db:
            # Tránh f-string với nested quotes: build escaped value rồi dùng format()
            esc_target = target_db.replace("'", "''")
            sql_lines += [
                "-- Ensure SINGLE_USER on [{}] for overwrite".format(esc_target),
                "IF DB_ID(N'{}') IS NOT NULL".format(esc_target),
                "BEGIN",
                "  ALTER DATABASE {} SET SINGLE_USER WITH ROLLBACK IMMEDIATE;".format(qTarget),
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
                    # STOPAT + RECOVERY
                    sql_lines.append("-- RESTORE LOG (final, STOPAT)")
                    sql_lines.append(f"RESTORE LOG {qTarget} FROM {fd}")
                    sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, STOPAT = '{stopat.isoformat(sep=' ')}', RECOVERY;\n")
                elif final and not final_contains:
                    # RECOVERY không STOPAT
                    sql_lines.append("-- RESTORE LOG (final)")
                    sql_lines.append(f"RESTORE LOG {qTarget} FROM {fd}")
                    sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, RECOVERY;\n")
                else:
                    # NORECOVERY
                    sql_lines.append("-- RESTORE LOG")
                    sql_lines.append(f"RESTORE LOG {qTarget} FROM {fd}")
                    sql_lines.append(f"WITH {'CHECKSUM, ' if use_checksum else ''}STATS = {stats_n}, NORECOVERY;\n")
        else:
            # Không có LOG nào -> RECOVERY ngay sau DIFF/FULL
            sql_lines.append("-- No LOGs selected -> RECOVERY at FULL/DIFF")
            sql_lines.append(f"RESTORE DATABASE {qTarget} WITH RECOVERY;\n")

        # Back to MULTI_USER nếu đè DB gốc
        if target_db == db:
            sql_lines += [
                f"-- Back to MULTI_USER on [{target_db}]",
                f"ALTER DATABASE {qTarget} SET MULTI_USER;"
            ]

        # Lắp TEMPLATE đầy đủ:
        full_sql = self._make_full_restore_script(
            source_db=db,
            target_db=target_db,
            stopat_iso=(None if (stopat is None) else stopat.isoformat(timespec="seconds")),
            overwrite=overwrite,
            relocate=relocate,
            data_path=data_path,
            log_path=log_path,
            tail_log_file=tail_file,
            manage_single_user=True,     # bạn có thể nối với 1 checkbox nếu muốn bật tắt
            use_checksum=True,
            stats_n=5,
            dry_run=generate_only,
        )

        # Hiển thị hoặc thực thi
        self._clear_log()
        if generate_only:
            self._log(full_sql)
            messagebox.showinfo("Script sẵn sàng", "Script đã hiển thị trong ô trạng thái.\nCopy và dán vào SSMS để chạy.")
        else:
            try:
                cur = self.owner.conn.cursor()
                cur.execute(full_sql)     # full_sql KHÔNG chứa GO
                self.owner.conn.commit()
                self._log("✓ Khôi phục hoàn tất.")
                self._log("Nếu trong quá trình khôi phục có lỗi, Sử dụng script hiển thị để chạy lại trong SQL Server Management Studio để biết chi tiết.")
                self._log("Để hủy tiến trình khôi phục đang chạy, sử dụng câu lệnh: RESTORE DATABASE [Database_Name] WITH RECOVERY;")
                messagebox.showinfo("Thành công", "Khôi phục hoàn tất.")
            except Exception as e:
                self._log(f"✗ Lỗi khôi phục: {e}")
                messagebox.showerror("Lỗi khôi phục", str(e))

    def _make_full_restore_script(
        self,
        source_db: str,
        target_db: str,
        stopat_iso: str | None,
        overwrite: bool,
        relocate: bool,
        data_path: str,
        log_path: str,
        tail_log_file: str | None,
        manage_single_user: bool,
        use_checksum: bool = True,
        stats_n: int = 5,
        dry_run: bool = False,
    ) -> str:
        """
        Lắp đầy đủ TEMPLATE script như bạn yêu cầu.
        - stopat_iso: None => @StopAt = NULL (mới nhất)
        - overwrite -> @Overwrite
        - relocate  -> @Relocate (+ DataPath/LogPath)
        - tail_log_file -> @TailLogFile
        - manage_single_user -> @ManageSingleUser
        - dry_run -> @DryRun
        """
        def q(s: str) -> str:
            return s.replace("'", "''")

        stopat_literal = "NULL" if stopat_iso is None else f"'{q(stopat_iso)}'"

        return f"""/* ================================================================
    AUTO RESTORE (generated by UI)
    - FULL base (non COPY_ONLY) → DIFF khớp → LOGs tới/bao trùm @StopAt
    - Tuỳ chọn Tail Log, SINGLE_USER/MULTI_USER, MOVE file
    ================================================================ */

    SET NOCOUNT ON;
    USE master;

    ------------------------ CẤU HÌNH (auto-filled) ------------------------
    DECLARE @SourceDb       sysname       = N'{q(source_db)}';
    DECLARE @TargetDb       sysname       = N'{q(target_db)}';
    DECLARE @StopAt         datetime      = {stopat_literal};     -- NULL = mới nhất
    DECLARE @Overwrite      bit           = {1 if overwrite else 0};
    DECLARE @DryRun         bit           = {1 if dry_run else 0};
    DECLARE @UseChecksum    bit           = {1 if use_checksum else 0};
    DECLARE @UseStats       int           = {stats_n};
    DECLARE @Relocate       bit           = {1 if relocate else 0};
    DECLARE @DataPath       nvarchar(260) = N'{q(data_path)}';
    DECLARE @LogPath        nvarchar(260) = N'{q(log_path)}';

    -- Tính năng bổ sung:
    DECLARE @TailLogFile    nvarchar(4000)= { 'NULL' if not tail_log_file else "N'"+q(tail_log_file)+"'" };
    DECLARE @ManageSingleUser bit         = {1 if manage_single_user else 0};
    ------------------------------------------------------------------------

    IF @StopAt IS NULL SET @StopAt = '9999-12-31';

    -- [PHẦN CÒN LẠI GIỮ NGUYÊN THEO TEMPLATE CỦA BẠN]
    -- NGUYÊN VĂN: (mình dán 1:1, chỉ bỏ các comment quá dài cho gọn)
    -- BẮT ĐẦU TEMPLATE -----------------------------------------------

    -- Kiểm tra msdb có lịch sử backup cho @SourceDb
    IF NOT EXISTS (SELECT 1 FROM msdb.dbo.backupset WHERE database_name = @SourceDb)
    BEGIN
        RAISERROR(N'Không thấy lịch sử backup của %s trong msdb.', 16, 1, @SourceDb);
        RETURN;
    END;

    -- 1)Tìm FULL backup (non COPY_ONLY) trước/bằng Thời điểm khôi phục dữ liệu
    IF OBJECT_ID('tempdb..#base') IS NOT NULL DROP TABLE #base;
    SELECT TOP (1) *
    INTO #base
    FROM msdb.dbo.backupset
    WHERE database_name = @SourceDb
        AND type = 'D'               -- FULL
        AND is_copy_only = 0
        AND backup_finish_date <= @StopAt
    ORDER BY backup_finish_date DESC;

    IF NOT EXISTS (SELECT 1 FROM #base)
    BEGIN
        RAISERROR(N'Không tìm thấy FULL backup (không COPY_ONLY) trước/bằng @StopAt.', 16, 1);
        RETURN;
    END;

    -- 2) Tệp FULL (gồm striping)
    IF OBJECT_ID('tempdb..#base_files') IS NOT NULL DROP TABLE #base_files;
    SELECT bmf.physical_device_name, bmf.family_sequence_number
    INTO #base_files
    FROM msdb.dbo.backupmediafamily bmf
    JOIN #base b ON bmf.media_set_id = b.media_set_id
    ORDER BY bmf.family_sequence_number;

    -- 3) DIFF khớp base
    IF OBJECT_ID('tempdb..#diff') IS NOT NULL DROP TABLE #diff;
    WITH d AS (
        SELECT TOP (1) *
        FROM msdb.dbo.backupset
        WHERE database_name = @SourceDb
            AND type = 'I'
            AND backup_finish_date <= @StopAt
            AND backup_start_date > (SELECT backup_start_date FROM #base)
            AND differential_base_lsn = (SELECT first_lsn FROM #base)
        ORDER BY backup_finish_date DESC
    )
    SELECT * INTO #diff FROM d;

    -- tệp DIFF (nếu có)
    IF OBJECT_ID('tempdb..#diff_files') IS NOT NULL DROP TABLE #diff_files;
    IF EXISTS (SELECT 1 FROM #diff)
    BEGIN
        SELECT bmf.physical_device_name, bmf.family_sequence_number
        INTO #diff_files
        FROM msdb.dbo.backupmediafamily bmf
        JOIN #diff d ON bmf.media_set_id = d.media_set_id
        ORDER BY bmf.family_sequence_number;
    END;

    -- 4) LOGs sau DIFF (nếu có) hoặc sau FULL
    DECLARE @StartLsn numeric(25,0) =
        COALESCE( (SELECT TOP(1) last_lsn FROM #diff ORDER BY last_lsn DESC), (SELECT last_lsn FROM #base) );

    IF OBJECT_ID('tempdb..#logs_all') IS NOT NULL DROP TABLE #logs_all;
    CREATE TABLE #logs_all
    (
        backup_set_id        int,
        media_set_id         int,
        database_name        sysname,
        [type]               char(1),
        is_copy_only         bit,
        backup_start_date    datetime,
        backup_finish_date   datetime,
        first_lsn            numeric(25,0),
        last_lsn             numeric(25,0),
        database_backup_lsn  numeric(25,0)
    );

    INSERT INTO #logs_all (backup_set_id, media_set_id, database_name, [type], is_copy_only,
                        backup_start_date, backup_finish_date, first_lsn, last_lsn, database_backup_lsn)
    SELECT backup_set_id, media_set_id, database_name, [type], is_copy_only,
        backup_start_date, backup_finish_date, first_lsn, last_lsn, database_backup_lsn
    FROM msdb.dbo.backupset
    WHERE database_name = @SourceDb
        AND [type] = 'L'
        AND last_lsn > @StartLsn
    ORDER BY backup_finish_date ASC;

    IF OBJECT_ID('tempdb..#logs_sel') IS NOT NULL DROP TABLE #logs_sel;
    CREATE TABLE #logs_sel
    (
        backup_set_id        int,
        media_set_id         int,
        database_name        sysname,
        [type]               char(1),
        is_copy_only         bit,
        backup_start_date    datetime,
        backup_finish_date   datetime,
        first_lsn            numeric(25,0),
        last_lsn             numeric(25,0),
        database_backup_lsn  numeric(25,0)
    );

    -- Lấy danh sách các bản log backup trước thời điểm khôi phục dữ liệu từ bảng logs_all
    INSERT INTO #logs_sel (backup_set_id, media_set_id, database_name, [type], is_copy_only,
                        backup_start_date, backup_finish_date, first_lsn, last_lsn, database_backup_lsn)
    SELECT backup_set_id, media_set_id, database_name, [type], is_copy_only,
        backup_start_date, backup_finish_date, first_lsn, last_lsn, database_backup_lsn
    FROM #logs_all
    WHERE backup_finish_date < @StopAt
    ORDER BY backup_finish_date ASC;

    DECLARE @DayStart      datetime = DATEADD(day, DATEDIFF(day, 0, @StopAt ), 0);
    DECLARE @NextDayStart  datetime = DATEADD(day, 1, @DayStart);

    DECLARE @finalLogId int =
    (
        SELECT TOP (1) backup_set_id
        FROM #logs_all
        WHERE backup_finish_date >= @StopAt
        AND backup_start_date  >= @DayStart
        AND backup_finish_date <  @NextDayStart
        ORDER BY backup_finish_date ASC
    );

    IF @finalLogId IS NOT NULL
    BEGIN
        INSERT INTO #logs_sel (backup_set_id, media_set_id, database_name, [type], is_copy_only,
                                backup_start_date, backup_finish_date, first_lsn, last_lsn, database_backup_lsn)
        SELECT backup_set_id, media_set_id, database_name, [type], is_copy_only,
                backup_start_date, backup_finish_date, first_lsn, last_lsn, database_backup_lsn
        FROM #logs_all
        WHERE backup_set_id = @finalLogId;
    END

    DECLARE @hasLogs int = (SELECT COUNT(*) FROM #logs_sel);
    DECLARE @lastLogId int =
    (
        SELECT TOP (1) backup_set_id
        FROM #logs_sel
        ORDER BY backup_finish_date DESC
    );

    -- MOVE list (từ backupfile của FULL base)
    IF OBJECT_ID('tempdb..#bf') IS NOT NULL DROP TABLE #bf;
    SELECT bf.logical_name, bf.physical_name, bf.file_type, bf.file_number
    INTO #bf
    FROM msdb.dbo.backupfile bf
    JOIN #base b ON bf.backup_set_id = b.backup_set_id;

    IF OBJECT_ID('tempdb..#bf2') IS NOT NULL DROP TABLE #bf2;
    ;WITH x AS (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY file_type ORDER BY file_number) AS rn
        FROM #bf
    )
    SELECT logical_name, file_type, rn, physical_name,
        CASE
            WHEN RIGHT(LOWER(physical_name), 4) IN ('.mdf', '.ndf', '.ldf')
            THEN RIGHT(physical_name, 4)
            ELSE CASE WHEN file_type='L' THEN '.ldf' ELSE CASE WHEN rn=1 THEN '.mdf' ELSE '.ndf' END END
        END AS ext,
        CASE WHEN 1 = 1 THEN
            CASE WHEN file_type='L'
                THEN @LogPath  + @TargetDb + CASE WHEN rn=1 THEN '_log' ELSE '_log' + CAST(rn AS varchar(10)) END
                ELSE @DataPath + @TargetDb + CASE WHEN rn=1 THEN ''     ELSE '_' + CAST(rn AS varchar(10)) END
            END
            ELSE physical_name
        END AS dest_base
    INTO #bf2
    FROM x;

    DECLARE @MoveClause nvarchar(max) =
        STUFF((
        SELECT N', MOVE N''' + logical_name + N''' TO N''' +
                REPLACE(dest_base, '''', '''''') + ext + N''''
        FROM #bf2
        ORDER BY (CASE WHEN file_type='D' THEN 0 ELSE 1 END), rn
        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');

    DECLARE @FromBase nvarchar(max) =
        STUFF((
        SELECT N', DISK = N''' + REPLACE(physical_device_name, '''', '''''') + N''''
        FROM #base_files
        ORDER BY family_sequence_number
        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');

    DECLARE @FromDiff nvarchar(max) = NULL;
    IF EXISTS (SELECT 1 FROM #diff)
    BEGIN
        SET @FromDiff =
        STUFF((
        SELECT N', DISK = N''' + REPLACE(physical_device_name, '''', '''''') + N''''
        FROM #diff_files
        ORDER BY family_sequence_number
        FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');
    END;

    DECLARE @sql nvarchar(max) = N'';
    DECLARE @optsCommon nvarchar(200) =
        N'WITH ' + CASE WHEN @UseChecksum=1 THEN N'CHECKSUM, ' ELSE N'' END +
        N'STATS = ' + CAST(@UseStats AS nvarchar(10)) + N', ';

    DECLARE @WillUseTail bit =
        CASE WHEN @TailLogFile IS NOT NULL AND @TargetDb = @SourceDb THEN 1 ELSE 0 END;

    DECLARE @qTargetDb sysname = QUOTENAME(@TargetDb);
    DECLARE @TailFileEsc nvarchar(4000) = REPLACE(COALESCE(@TailLogFile,N''), '''', '''''');

    IF @ManageSingleUser = 1 AND @TargetDb = @SourceDb
    BEGIN
        SET @sql += N'-- Ensure exclusive access' + CHAR(13) +
                    N'IF DB_ID(N''' + REPLACE(@TargetDb, '''', '''''') + N''') IS NOT NULL' + CHAR(13) +
                    N'BEGIN' + CHAR(13) +
                    N'  IF (SELECT state_desc FROM sys.databases WHERE name = N''' + REPLACE(@TargetDb, '''', '''''') + N''') = ''ONLINE''' + CHAR(13) +
                    N'  BEGIN' + CHAR(13) +
                    N'    DECLARE @sid int;' + CHAR(13) +
                    N'    DECLARE @sql NVARCHAR(100);' + CHAR(13) +
                    N'    DECLARE kill_c CURSOR LOCAL FOR ' + CHAR(13) +
                    N'      SELECT session_id FROM sys.dm_exec_sessions WHERE database_id = DB_ID(N''' + REPLACE(@TargetDb, '''', '''''') + N''') AND session_id <> @@SPID;' + CHAR(13) +
                    N'    OPEN kill_c; FETCH NEXT FROM kill_c INTO @sid;' + CHAR(13) +
                    N'    WHILE @@FETCH_STATUS = 0 BEGIN Set @sql = (''KILL '' + CONVERT(NVARCHAR(20), @sid)); EXEC (@sql); FETCH NEXT FROM kill_c INTO @sid; END' + CHAR(13) +
                    N'    CLOSE kill_c; DEALLOCATE kill_c;' + CHAR(13) +
                    N'    ALTER DATABASE ' + @qTargetDb + N' SET SINGLE_USER WITH ROLLBACK IMMEDIATE;' + CHAR(13) +
                    N'  END' + CHAR(13) +
                    N'END' + CHAR(13) + CHAR(13);
    END

    -- RESTORE FULL
    IF @TargetDb = @SourceDb
    BEGIN
        SET @sql += N'RESTORE DATABASE ' + @qTargetDb + N' FROM ' + @FromBase + CHAR(13) +
                    @optsCommon + CASE WHEN @Overwrite=1 THEN N'REPLACE, ' ELSE N'' END + N'NORECOVERY;' + CHAR(13) + CHAR(13);
    END
    ELSE
    BEGIN
        SET @sql += N'RESTORE DATABASE ' + @qTargetDb + N' FROM ' + @FromBase + CHAR(13) +
                    @optsCommon + CASE WHEN @Overwrite=1 THEN N'REPLACE, ' ELSE N'' END + N'NORECOVERY ' +
                    CASE WHEN @Relocate=1 THEN @MoveClause ELSE N'' END + N';' + CHAR(13) + CHAR(13);
    END

    -- RESTORE DIFF (nếu có)
    IF @FromDiff IS NOT NULL
        SET @sql += N'RESTORE DATABASE ' + @qTargetDb + N' FROM ' + @FromDiff + CHAR(13) +
                    @optsCommon + N'NORECOVERY;' + CHAR(13) + CHAR(13);

    -- LOGs
    IF @hasLogs > 0
    BEGIN
        DECLARE @media_set_id int, @fromLog nvarchar(max), @isFinal bit;

        DECLARE cur CURSOR LOCAL FAST_FORWARD FOR
            SELECT media_set_id,
                CASE 
                WHEN @finalLogId IS NOT NULL AND backup_set_id = @finalLogId THEN 1
                WHEN @finalLogId IS NULL AND backup_set_id = @lastLogId THEN 1
                ELSE 0
                END AS is_final
            FROM #logs_sel
            ORDER BY backup_finish_date ASC;

        OPEN cur; FETCH NEXT FROM cur INTO @media_set_id, @isFinal;
        WHILE @@FETCH_STATUS = 0
        BEGIN
            SET @fromLog = STUFF((
                SELECT N', DISK = N''' + REPLACE(physical_device_name, '''', '''''') + N''''
                FROM msdb.dbo.backupmediafamily
                WHERE media_set_id = @media_set_id
                ORDER BY family_sequence_number
                FOR XML PATH(''), TYPE).value('.', 'nvarchar(max)'), 1, 2, '');

            IF @WillUseTail = 1
                SET @sql += N'RESTORE LOG ' + @qTargetDb + N' FROM ' + @fromLog + CHAR(13) +
                            @optsCommon + N'NORECOVERY;' + CHAR(13) + CHAR(13);
            ELSE
            BEGIN
                IF @isFinal = 1 AND @finalLogId IS NOT NULL
                    SET @sql += N'RESTORE LOG ' + @qTargetDb + N' FROM ' + @fromLog + CHAR(13) +
                                N'WITH ' + CASE WHEN @UseChecksum=1 THEN N'CHECKSUM, ' ELSE N'' END +
                                N'STATS = ' + CAST(@UseStats AS nvarchar(10)) +
                                N', STOPAT = ''' + CONVERT(nvarchar(23), @StopAt, 121) + N''', RECOVERY;' + CHAR(13) + CHAR(13);
                ELSE IF @isFinal = 1 AND @finalLogId IS NULL
                    SET @sql += N'RESTORE LOG ' + @qTargetDb + N' FROM ' + @fromLog + CHAR(13) +
                                N'WITH ' + CASE WHEN @UseChecksum=1 THEN N'CHECKSUM, ' ELSE N'' END +
                                N'STATS = ' + CAST(@UseStats AS nvarchar(10)) + N', RECOVERY;' + CHAR(13) + CHAR(13);
                ELSE
                    SET @sql += N'RESTORE LOG ' + @qTargetDb + N' FROM ' + @fromLog + CHAR(13) +
                                @optsCommon + N'NORECOVERY;' + CHAR(13) + CHAR(13);
            END

            FETCH NEXT FROM cur INTO @media_set_id, @isFinal;
        END
        CLOSE cur; DEALLOCATE cur;
    END
    ELSE
    BEGIN
        IF @WillUseTail = 0
            SET @sql += N'RESTORE DATABASE ' + @qTargetDb + N' WITH RECOVERY;' + CHAR(13) + CHAR(13);
    END

    -- TAIL (nếu có & ghi đè DB gốc)
    IF @WillUseTail = 1
    BEGIN
        SET @sql += N'RESTORE LOG ' + @qTargetDb + N' FROM DISK = N''' + @TailFileEsc + N''' ' + CHAR(13) +
                    N'WITH ' + CASE WHEN @UseChecksum=1 THEN N'CHECKSUM, ' ELSE N'' END +
                    N'STATS = ' + CAST(@UseStats AS nvarchar(10)) +
                    CASE WHEN @StopAt >= '9999-12-31'
                        THEN N', RECOVERY'
                        ELSE N', STOPAT = ''' + CONVERT(nvarchar(23), @StopAt, 121) + N''', RECOVERY' END + N';' + CHAR(13) + CHAR(13);
    END

    IF @ManageSingleUser = 1 AND @TargetDb = @SourceDb
    BEGIN
        SET @sql += N'IF DB_ID(N''' + REPLACE(@TargetDb, '''', '''''') + N''') IS NOT NULL ALTER DATABASE ' + @qTargetDb + N' SET MULTI_USER;' + CHAR(13) + CHAR(13);
    END

    DECLARE @BaseFinish nvarchar(30), @DiffFinish nvarchar(30) = NULL, @LogCount int;
    SELECT @BaseFinish = CONVERT(nvarchar(30), backup_finish_date, 121) FROM #base;
    IF EXISTS (SELECT 1 FROM #diff)
        SELECT @DiffFinish = CONVERT(nvarchar(30), backup_finish_date, 121) FROM #diff;
    SELECT @LogCount = COUNT(*) FROM #logs_sel;

    PRINT '--- SUMMARY -------------------------------------------';
    PRINT 'Time Restore: ' + CAST(@StopAt AS nvarchar(20));
    PRINT 'Base FULL   : ' + ISNULL(@BaseFinish,'(none)');
    PRINT 'DIFF        : ' + ISNULL(@DiffFinish,'(none)');
    PRINT 'LOG count   : ' + CAST(@LogCount AS nvarchar(10));
    PRINT 'Target DB   : ' + @TargetDb;
    PRINT 'Relocate    : ' + CAST(@Relocate AS nvarchar(10));
    PRINT 'Overwrite   : ' + CAST(@Overwrite AS nvarchar(10));
    PRINT 'Tail file   : ' + ISNULL(@TailLogFile, '(none)');
    PRINT 'DryRun      : ' + CAST(@DryRun   AS nvarchar(10));
    PRINT '-------------------------------------------------------';

    IF @DryRun = 1
    BEGIN
        PRINT @sql;
    END
    ELSE
    BEGIN
        EXEC sp_executesql @sql;
    END
    -- HẾT TEMPLATE ----------------------------------------------------
    """
