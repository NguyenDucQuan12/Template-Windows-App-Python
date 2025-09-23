# -*- coding: utf-8 -*-
"""
LogsFrame (msdb) — tải nền + debounce resize + fill toàn khung
----------------------------------------------------------------
- Query msdb.dbo.backupset/backupmediafamily trong luồng nền (thread)
- Render 1 lần; khi resize chỉ update wraplength cho cột "Tệp tạo"
- Có overlay "Đang tải..." để báo trạng thái
- Bảng chiếm toàn bộ diện tích frame (grid weights)
"""

import threading
import datetime as dt
from typing import List, Dict, Any, Optional, Tuple

import customtkinter as ctk
from tkinter import messagebox

# ================== TIỆN ÍCH KẾT NỐI/SQL ====================

def _test_connection(conn) -> bool:
    """Thử SELECT 1: True nếu kết nối dùng được."""
    try:
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        return True
    except Exception:
        return False

def run_sql_safe(conn, sql: str, params: tuple = (), autocommit: bool = True):
    """
    Thực thi SQL an toàn, trả (ok, msg, rows).
    - Không raise exception ra ngoài để UI xử lý thân thiện.
    - Bật autocommit tạm thời (nếu có thuộc tính).
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
            if cur: cur.close()
        except Exception:
            pass
        try:
            conn.autocommit = prev
        except Exception:
            pass


# ========================= FRAME ============================

class LogsFrame(ctk.CTkFrame):
    """
    Hiển thị lịch sử backup từ SQL Server (msdb):
      - Lọc DB: (Tất cả) hoặc 1 DB
      - Giới hạn số bản ghi
      - Tải msdb dưới nền (thread), render 1 lần
      - Resize: chỉ update wraplength, KHÔNG vẽ lại toàn bộ
    """

    # ƯỚC LƯỢNG độ rộng 4 cột đầu (px) để tính wrap cho cột "files"
    COL_W_TS     = 180
    COL_W_DB     = 180
    COL_W_TYPE   = 110
    COL_W_STATUS = 140
    COL_PADDING  = 48   # tổng padding/spacing ước lượng

    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        # Dữ liệu hiện tại (cache render)
        self._data_rows: List[Dict[str, Any]] = []
        # Giới hạn mặc định
        self.max_rows = 300
        # Danh sách label của cột files để cập nhật wraplength khi resize
        self._file_labels: List[ctk.CTkLabel] = []
        self._fixed_labels: List[Tuple[ctk.CTkLabel, int]] = []  # (label, width_px) cho 4 cột đầu

        # ============ Layout cha: 2 hàng (toolbar, table), fill all ============
        self.grid_rowconfigure(1, weight=1)      # bảng chiếm hết
        self.grid_columnconfigure(0, weight=1)   # fill chiều ngang

        ctk.CTkLabel(self, text="Lịch sử sao lưu (msdb)", font=ctk.CTkFont(size=16, weight="bold"))\
            .grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        self._build_toolbar()
        self._build_table()

        # Lần đầu nạp ds DB và dữ liệu
        self._load_db_list()
        self.reload()

        # Debounce resize: chỉ update wraplength, không render lại
        # GẮN SỰ KIỆN TRÊN CONTAINER LỚN (self.table_wrap) thay vì ScrollableFrame bên trong
        self.table_wrap.bind("<Configure>", self._on_container_resize)

    # ----------------- UI: thanh công cụ -----------------

    def _build_toolbar(self):
        bar = ctk.CTkFrame(self)
        bar.grid(row=0, column=0, padx=12, pady=(0, 6), sticky="e")
        bar.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(bar, text="CSDL:").grid(row=0, column=0, padx=(4, 6), pady=6, sticky="e")
        self.cbo_db = ctk.CTkComboBox(bar, values=["(đang tải...)"], width=240, command=lambda _: self.reload())
        self.cbo_db.grid(row=0, column=1, padx=(0, 8), pady=6, sticky="w")

        ctk.CTkLabel(bar, text="Giới hạn:").grid(row=0, column=2, padx=(16, 6), pady=6, sticky="e")
        self.cbo_limit = ctk.CTkComboBox(bar, values=["100", "200", "300", "500", "1000"], width=100,
                                         command=lambda _: self.reload())
        self.cbo_limit.set(str(self.max_rows))
        self.cbo_limit.grid(row=0, column=3, padx=(0, 8), pady=6, sticky="w")

        ctk.CTkButton(bar, text="↻ Làm mới", command=self.reload)\
            .grid(row=0, column=4, padx=(8, 4), pady=6, sticky="w")

    # ----------------- UI: bảng & overlay -----------------

    def _build_table(self):
        """
        table_wrap: khung chứa header + scrollable frame
        ├─ header_frame: dòng tiêu đề
        └─ sf: CTkScrollableFrame chứa dữ liệu
        """
        self.table_wrap = ctk.CTkFrame(self)
        self.table_wrap.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="nsew")
        self.table_wrap.grid_rowconfigure(1, weight=1)
        self.table_wrap.grid_columnconfigure(0, weight=1)

        # Header
        header = ctk.CTkFrame(self.table_wrap)
        header.grid(row=0, column=0, sticky="ew")
        for i in range(5):
            header.grid_columnconfigure(i, weight=(1 if i == 4 else 0))

        hdr_font = ctk.CTkFont(weight="bold")

        def _hdr(text, col, w=None):
            lbl = ctk.CTkLabel(header, text=text, font=hdr_font, anchor="w", justify="left")
            if w is not None:
                lbl.configure(width=w)
            lbl.grid(row=0, column=col, padx=(6, 6), pady=(6, 6), sticky="w")
            return lbl

        _hdr("THỜI GIAN", 0, self.COL_W_TS)
        _hdr("DATABASE",  1, self.COL_W_DB)
        _hdr("LOẠI",      2, self.COL_W_TYPE)
        _hdr("KẾT QUẢ",   3, self.COL_W_STATUS)
        _hdr("TỆP TẠO",   4)  # cột này mở rộng

        # ScrollableFrame dữ liệu
        self.sf = ctk.CTkScrollableFrame(self.table_wrap, fg_color="transparent")
        self.sf.grid(row=1, column=0, sticky="nsew")
        for i in range(5):
            self.sf.grid_columnconfigure(i, weight=(1 if i == 4 else 0))

        # Overlay loading
        self.loading_overlay = ctk.CTkFrame(self.table_wrap)
        self.loading_overlay.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.loading_overlay.grid_rowconfigure(0, weight=1)
        self.loading_overlay.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.loading_overlay, text="Đang tải dữ liệu...",
                     font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, padx=12, pady=12)
        self.loading_overlay.lower()

    def _show_loading(self, show: bool):
        """Hiện/ẩn overlay loading mà KHÔNG block mainloop."""
        if show:
            self.loading_overlay.lift()
        else:
            self.loading_overlay.lower()

    # ====================== DATA =======================

    def _load_db_list(self):
        """Nạp combobox DB từ sys.databases."""
        conn = getattr(self.owner, "conn", None)
        if conn is None or not _test_connection(conn):
            self.cbo_db.configure(values=["(Tất cả)"])
            self.cbo_db.set("(Tất cả)")
            return
        ok, msg, rows = run_sql_safe(conn, "SELECT name FROM sys.databases ORDER BY name;")
        if not ok:
            messagebox.showerror("Lỗi nạp danh sách DB", msg)
            self.cbo_db.configure(values=["(Tất cả)"])
            self.cbo_db.set("(Tất cả)")
            return
        vals = ["(Tất cả)"] + [r[0] for r in (rows or [])]
        self.cbo_db.configure(values=vals)
        self.cbo_db.set(vals[0] if vals else "(Tất cả)")

    def reload(self):
        """
        Tải dữ liệu trong LUỒNG NỀN, xong gọi render trên main thread.
        """
        conn = getattr(self.owner, "conn", None)
        if conn is None or not _test_connection(conn):
            messagebox.showwarning("Chưa kết nối", "Bạn cần kết nối SQL Server trước.")
            return

        # Lấy limit an toàn
        try:
            self.max_rows = int(self.cbo_limit.get())
        except Exception:
            self.max_rows = 300
            self.cbo_limit.set(str(self.max_rows))

        # DB filter (None = tất cả)
        sel = (self.cbo_db.get() or "").strip()
        db_filter = None if (not sel or sel == "(Tất cả)") else sel

        # Hiện overlay
        self._show_loading(True)
        # Xoá dữ liệu cũ trên UI (không bắt buộc, chỉ để trống khi đang tải)
        self._clear_sf_rows()

        # Chạy nền
        threading.Thread(
            target=self._worker_query_msdb,
            args=(conn, db_filter, self.max_rows),
            daemon=True
        ).start()

    def _worker_query_msdb(self, conn, db_filter: Optional[str], limit: int):
        """
        Luồng nền: Query msdb.dbo.backupset và backupmediafamily, gom dữ liệu vào list dict.
        Sau đó chuyển về main thread bằng after().
        """
        # 1) Lấy bản ghi backup
        sql = f"""
SELECT TOP {limit}
    bs.backup_finish_date,
    bs.database_name,
    CASE bs.[type]
        WHEN 'D' THEN 'FULL'
        WHEN 'I' THEN 'DIFF'
        WHEN 'L' THEN 'LOG'
        ELSE bs.[type]
    END AS backup_type,
    COALESCE(CAST(bs.compressed_backup_size/1024/1024 AS BIGINT),
             CAST(bs.backup_size/1024/1024 AS BIGINT)) AS size_mb,
    bs.backup_set_id,
    bs.media_set_id,
    bs.is_copy_only
FROM msdb.dbo.backupset AS bs
WHERE ({'bs.database_name = ?' if db_filter else '1=1'})
ORDER BY bs.backup_finish_date DESC;
"""
        params = (db_filter,) if db_filter else ()
        ok, msg, rows = run_sql_safe(conn, sql, params=params)
        if not ok:
            # Chuyển về main thread để báo lỗi & ẩn overlay
            return self.after(0, lambda: (self._show_loading(False),
                                          messagebox.showerror("Lỗi truy vấn msdb", msg)))

        result: List[Dict[str, Any]] = []
        media_ids = set()
        for r in rows or []:
            (finish_dt, database_name, typ, size_mb, bset_id, media_set_id, is_copy_only) = r
            result.append({
                "ts": finish_dt,
                "db": database_name,
                "type": typ,
                "size_mb": int(size_mb or 0),
                "backup_set_id": int(bset_id or 0),
                "media_set_id": int(media_set_id or 0),
                "is_copy_only": bool(is_copy_only),
                "files": ""
            })
            media_ids.add(int(media_set_id or 0))

        # 2) Lấy file cho tất cả media_set_id bằng 1 truy vấn IN (...) batches nếu cần
        files_map: Dict[int, List[str]] = {}
        if media_ids:
            # Chia batch 200 id/lần để tránh câu quá dài
            media_list = list(media_ids)
            batch = 200
            for i in range(0, len(media_list), batch):
                chunk = media_list[i:i+batch]
                # Tạo placeholders ?,?,?... cho pyodbc
                placeholders = ",".join(["?"] * len(chunk))
                sql_f = f"""
SELECT media_set_id, physical_device_name, family_sequence_number
FROM msdb.dbo.backupmediafamily
WHERE media_set_id IN ({placeholders})
ORDER BY media_set_id, family_sequence_number;
"""
                ok, msg, rows_f = run_sql_safe(conn, sql_f, params=tuple(chunk))
                if not ok:
                    # Không fail toàn bộ, chỉ bỏ files_map của batch này
                    continue
                for mid, path, _seq in rows_f or []:
                    files_map.setdefault(int(mid or 0), []).append(path)

        # 3) Gắn files vào result
        for it in result:
            files = files_map.get(it["media_set_id"]) or []
            it["files"] = "; ".join(files)

        # 4) Chuyển về main thread: cập nhật cache + render + ẩn overlay
        self.after(0, lambda: self._apply_new_data(result))

    # ================== RENDER/RESIZE ====================

    def _apply_new_data(self, rows: List[Dict[str, Any]]):
        """Cập nhật cache & render UI; tắt overlay."""
        self._data_rows = rows
        self._render_rows()
        self._show_loading(False)

    def _clear_sf_rows(self):
        """Xoá mọi widget dữ liệu trong ScrollableFrame (giữ header ngoài)."""
        for w in self.sf.winfo_children():
            w.destroy()
        self._file_labels.clear()
        self._fixed_labels.clear()

    def _render_rows(self):
        """
        Vẽ lại dữ liệu trong ScrollableFrame. Gọi hàm này trên main thread.
        Chỉ gọi khi có data mới (tải xong) hoặc khi cần vẽ lần đầu.
        Resize KHÔNG gọi lại cái này (tránh đơ).
        """
        self._clear_sf_rows()

        # Tính wraplength cho cột "files" theo bề rộng container
        self._clear_sf_rows()
        files_w = self._compute_files_width_and_wrap()
        font_row = ctk.CTkFont(size=12)

        r = 0
        for it in self._data_rows:
            ts = it["ts"]
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S") if isinstance(ts, dt.datetime) else str(ts)
            tag = f"{it['type']}{' (COPY_ONLY)' if it.get('is_copy_only') else ''}"
            status_text = f"OK  •  {it.get('size_mb',0):,} MB"
            files_text = it.get("files") or "(không rõ thiết bị/đường dẫn)"

            # 4 cột đầu dùng width cố định + bám góc trên trái để thẳng hàng các hàng cao thấp khác nhau
            lab_ts = ctk.CTkLabel(self.sf, text=ts_str, font=font_row, anchor="w", justify="left",
                                  width=self.COL_W_TS)
            lab_ts.grid(row=r, column=0, padx=(6, 6), pady=(4, 4), sticky="nw")
            self._fixed_labels.append((lab_ts, self.COL_W_TS))

            lab_db = ctk.CTkLabel(self.sf, text=it["db"], font=font_row, anchor="w", justify="left",
                                  width=self.COL_W_DB)
            lab_db.grid(row=r, column=1, padx=(6, 6), pady=(4, 4), sticky="nw")
            self._fixed_labels.append((lab_db, self.COL_W_DB))

            lab_type = ctk.CTkLabel(self.sf, text=tag, font=font_row, anchor="w", justify="left",
                                    width=self.COL_W_TYPE)
            lab_type.grid(row=r, column=2, padx=(6, 6), pady=(4, 4), sticky="nw")
            self._fixed_labels.append((lab_type, self.COL_W_TYPE))

            lab_status = ctk.CTkLabel(self.sf, text=status_text, font=font_row, anchor="w", justify="left",
                                      width=self.COL_W_STATUS)
            lab_status.grid(row=r, column=3, padx=(6, 6), pady=(4, 4), sticky="nw")
            self._fixed_labels.append((lab_status, self.COL_W_STATUS))

            # Cột FILES chiếm phần còn lại + wrap
            lab_files = ctk.CTkLabel(self.sf, text=files_text, font=font_row,
                                     anchor="w", justify="left",
                                     wraplength=files_w, width=files_w)
            lab_files.grid(row=r, column=4, padx=(6, 6), pady=(4, 4), sticky="new")
            self._file_labels.append(lab_files)

            r += 1

    def _compute_files_width_and_wrap(self) -> int:
        """
        Tính wraplength cho cột files dựa trên bề rộng khung table_wrap.
        Không render lại, chỉ trả về wraplength.
        """
        total = max(500, self.table_wrap.winfo_width() or 1000)
        fixed = self.COL_W_TS + self.COL_W_DB + self.COL_W_TYPE + self.COL_W_STATUS + self.COL_PADDING
        return max(220, total - fixed)

    def _on_container_resize(self, _event=None):
        """
        Debounce resize: sau 120ms không còn resize nữa mới cập nhật wraplength
        cho cột files — KHÔNG re-render dữ liệu.
        """
        if self._resize_after_id:
            try:
                self.after_cancel(self._resize_after_id)
            except Exception:
                pass
            self._resize_after_id = None

        self._resize_after_id = self.after(120, self._update_files_wrap_only)

    def _update_files_wrap_only(self):
        """Chỉ cập nhật wraplength của các label cột files, tránh vẽ lại toàn bảng."""
        self._resize_after_id = None
        files_w = self._compute_files_width_and_wrap()
        for lbl in self._file_labels:
            try:
                lbl.configure(wraplength=files_w, width=files_w)
            except Exception:
                pass
        # Đồng thời đảm bảo 4 cột đầu giữ nguyên width (khi người dùng thay đổi DPI/scale)
        for lbl, w in self._fixed_labels:
            try:
                lbl.configure(width=w)
            except Exception:
                pass
