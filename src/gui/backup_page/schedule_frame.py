# -*- coding: utf-8 -*-
"""
- Chạy Task bằng tài khoản người dùng (Run whether user is logged on or not = True)
  => không mở cửa sổ, chạy nền thực sự, đòi hỏi /RU và /RP
- PS1 hỗ trợ SqlUser/SqlPass (khi tài khoản Windows không có quyền trên SQL)
- CRON → schtasks (mẫu phổ biến)
- Kiểm tra Task, tạo/xóa Task (tự nâng quyền UAC)
- Kiểm tra quyền ghi (BACKUP COPY_ONLY), backup thủ công
- Lưu/đọc cấu hình theo từng DB (owner.config["per_db"][db_name])
"""
import os
import re
import ctypes
import tempfile
import threading
import subprocess
import customtkinter as ctk
from tkinter import messagebox, filedialog
from typing import Dict, Any, Optional, Tuple, List

# ============================ HỖ TRỢ CRON ============================

_CRON_RE = re.compile(r"^\s*([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s+([^\s]+)\s*$")

def _parse_cron(expr: str) -> Tuple[str, str, str, str, str]:
    """Tách 5 trường CRON: phút, giờ, ngày-tháng, tháng, thứ."""
    m = _CRON_RE.match(expr or "")
    if not m:
        raise ValueError("Chuỗi CRON không hợp lệ (phải có 5 trường).")
    return m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)

def _dow_to_names(dow_field: str) -> List[str]:
    """
    Chuyển trường 'thứ' của CRON thành danh sách tên viết tắt MON..SUN.
    Hỗ trợ số (0..7), tên (MON..SUN), dải (MON-FRI), danh sách (MON,WED,FRI).
    """
    num_map = {0: "SUN", 7: "SUN", 1: "MON", 2: "TUE", 3: "WED", 4: "THU", 5: "FRI", 6: "SAT"}
    names = []
    field = (dow_field or "").strip().upper()
    if field in ("*", "?"):
        return []
    parts = [p.strip() for p in field.replace(" ", "").split(",") if p.strip()]
    order = ["SUN","MON","TUE","WED","THU","FRI","SAT"]

    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            if a.isalpha():
                ia = order.index(a[:3]); ib = order.index(b[:3])
                if ia <= ib: names.extend(order[ia:ib+1])
                else: names.extend(order[ia:] + order[:ib+1])
            else:
                ia = int(a); ib = int(b)
                rng = range(ia, ib+1) if ia <= ib else list(range(ia, 7)) + list(range(0, ib+1))
                for n in rng: names.append(num_map.get(n, ""))
        else:
            if p.isalpha(): names.append(p[:3])
            else: names.append(num_map.get(int(p), ""))

    out = []
    for n in names:
        if n and n not in out: out.append(n)
    return out

def _safe_time(minute: str, hour: str) -> str:
    """Chuẩn hoá giờ/phút → 'HH:MM' cho schtasks /ST (nếu '*' thì 00)."""
    def norm_int(x: str, hi: int) -> int:
        v = int(x)
        return 0 if v < 0 else hi if v > hi else v
    h = 0 if hour == "*" else norm_int(hour, 23)
    m = 0 if minute == "*" or minute.startswith("*/") else norm_int(minute, 59)
    return f"{h:02d}:{m:02d}"

def cron_to_schtasks_args(expr: str) -> Dict[str, str]:
    """
    Ánh xạ CRON (5 trường) sang tham số schtasks:
      - Mỗi N phút:  */N * * * *  → /SC MINUTE /MO N /DU 24:00 /ST 00:01
      - Hằng ngày   :   M H * * *  → /SC DAILY  /ST H:M
      - Hằng tuần   :   M H * * D  → /SC WEEKLY /D Dlist /ST H:M
      - Hàng tháng  :   M H DOM * * → /SC MONTHLY /D DOM /ST H:M (chỉ 1 ngày)
    """
    minute, hour, dom, mon, dow = _parse_cron(expr)

    # Mỗi N phút
    if minute.startswith("*/") and hour == "*" and dom == "*" and mon == "*" and dow == "*":
        try:
            n = int(minute[2:])
            if n <= 0: raise ValueError
        except Exception:
            raise ValueError("CRON không hợp lệ: '*/N * * * *' yêu cầu N > 0.")
        return {"type": "MINUTE", "st": "00:01", "mo": str(n), "du": "24:00"}

    # Hằng tuần
    dnames = _dow_to_names(dow)
    if dnames and dom == "*" and mon == "*" and hour != "*" and not minute.startswith("*/"):
        st = _safe_time(minute, hour)
        return {"type": "WEEKLY", "st": st, "dlist": ",".join(dnames)}

    # Hằng ngày
    if dom == "*" and mon == "*" and dow in ("*", "?") and hour != "*" and not minute.startswith("*/"):
        st = _safe_time(minute, hour)
        return {"type": "DAILY", "st": st}

    # Hàng tháng (DOM = 1..31)
    if mon in ("*",) and dow in ("*", "?") and hour != "*" and dom not in ("*", "?",):
        if "," in dom or "-" in dom:
            raise ValueError("CRON hàng tháng chỉ hỗ trợ 1 ngày cố định (vd: '0 2 1 * *').")
        try:
            day_num = int(dom)
            if not (1 <= day_num <= 31): raise ValueError
        except Exception:
            raise ValueError("Giá trị ngày-tháng (DOM) không hợp lệ 1..31.")
        st = _safe_time(minute, hour)
        return {"type": "MONTHLY", "st": st, "dom": str(day_num)}

    raise ValueError("CRON chưa hỗ trợ ánh xạ sang schtasks (mẫu quá phức tạp).")

# ======================= LỚP GIAO DIỆN CHÍNH BACKUP =======================

class ScheduleFrame(ctk.CTkFrame):
    """
    Khung “Kịch bản Backup”:
      - Chọn DB, thư mục backup
      - Lịch CRON (tham khảo → ánh xạ schtasks)
      - Tạo script PS1 (ghi lịch sử)
      - Tạo/Xoá Task (run whether user is logged on or not) → bắt buộc nhập RU/RP
      - Hiển thị lệnh để copy
      - Backup thủ công
    """

    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page
        self.current_db: Optional[str] = None
        self.owner.config.setdefault("per_db", {})

        # Bố cục tổng thể
        self.grid_rowconfigure(6, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Kịch bản Backup", font=ctk.CTkFont(size=18, weight="bold"))\
            .grid(row=0, column=0, padx=16, pady=(16, 8), sticky="w")

        self._build_db_selector(row=1)
        self._build_storage(row=2)
        self._build_schedule(row=3)
        self._build_manual_backup(row=4)
        self._build_task_scheduler(row=5)

        # Khung log trạng thái
        self.status_box = ctk.CTkTextbox(self, width=1, height=1, wrap = "word", font=ctk.CTkFont(family="Consolas", size=11))
        self.status_box.grid(row=6, column=0, padx=16, pady=(6, 16), sticky="nsew")
        self._log("• Chọn CSDL, nhập thư mục đích, cấu hình CRON, tạo PS1, lập lịch bằng schtasks, hoặc backup thủ công.")

        # Khởi tạo DB đang chọn
        self._init_db_selection()

    # ------------------------ Khối UI: chọn DB ------------------------

    def _build_db_selector(self, row: int):
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(wrap, text="Chọn CSDL:").grid(row=0, column=0, padx=(12, 8), pady=8, sticky="e")

        values = sorted(list(self.owner.selected_databases)) if hasattr(self.owner, "selected_databases") else []
        self.cbo_db = ctk.CTkComboBox(wrap, values=values, width=260, command=lambda _: self._on_change_db())
        self.cbo_db.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        ctk.CTkButton(wrap, text="↻ Tải danh sách CSDL", command=self._reload_db_list)\
            .grid(row=0, column=2, padx=8, pady=8, sticky="w")

    # --------------------- Khối UI: thư mục lưu trữ ---------------------

    def _build_storage(self, row: int):
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(wrap, text="Thư mục lưu trữ (trên máy SQL Server):").grid(row=0, column=0, padx=(12, 8), pady=8, sticky="e")
        self.ent_dir = ctk.CTkEntry(wrap, width=460, placeholder_text=r"VD: E:\SQL_Backup\ hoặc \\server\share\backup")
        self.ent_dir.grid(row=0, column=1, padx=8, pady=8, sticky="w")

        ctk.CTkButton(wrap, text="Chọn thư mục", command=self._choose_local_dir)\
            .grid(row=0, column=2, padx=8, pady=8, sticky="w")

        ctk.CTkButton(wrap, text="Kiểm tra quyền ghi từ SQL Server", command=self._test_write_perm_model)\
            .grid(row=1, column=1, padx=8, pady=(0, 8), sticky="w")

        # Lưu ngay khi rời ô nhập
        self.ent_dir.bind("<FocusOut>", lambda _: self._persist_for_current_db())

    # --------------------- Khối UI: lịch (CRON tham khảo) ---------------------

    def _build_schedule(self, row: int):
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)
        wrap.grid_columnconfigure(2, weight=1)

        ctk.CTkLabel(wrap, text="Lịch FULL (CRON):").grid(row=0, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_full = ctk.CTkEntry(wrap, width=320); self.ent_full.grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Lịch DIFF (CRON):").grid(row=1, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_diff = ctk.CTkEntry(wrap, width=320); self.ent_diff.grid(row=1, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Lịch LOG (CRON):").grid(row=2, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_log  = ctk.CTkEntry(wrap, width=320); self.ent_log.grid(row=2, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkButton(wrap, text="💾 Lưu lịch", command=self._save_schedule)\
            .grid(row=3, column=1, padx=8, pady=(6, 8), sticky="w")

        cron_note = (
            "CRON 5 trường: phút giờ ngày-tháng tháng thứ\n"
            "Ví dụ:\n"
            "      0 0 * * 0      → Chủ nhật 00:00 (FULL)\n"
            "      30 0 * * 1-6   → T2–T7 00:30 (DIFF)\n"
            "      */15 * * * *   → Mỗi 15 phút (LOG)\n"
            "      0 2 1 * *      → Mùng 1 hàng tháng vào lúc 02:00"
        )
        ctk.CTkLabel(wrap, text=cron_note, justify="left", anchor="nw")\
            .grid(row=0, column=2, rowspan=4, padx=12, pady=6, sticky="nsew")

    # --------------------- Khối UI: backup thủ công ---------------------

    def _build_manual_backup(self, row: int):
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")

        ctk.CTkLabel(wrap, text="Backup thủ công:", font=ctk.CTkFont(weight="bold"))\
            .grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        ctk.CTkLabel(wrap, text="Kiểu:").grid(row=1, column=0, padx=(12, 8), pady=6, sticky="e")
        self.cbo_type = ctk.CTkComboBox(wrap, values=["FULL", "DIFF", "LOG"], width=120)
        self.cbo_type.grid(row=1, column=1, padx=8, pady=6, sticky="w"); self.cbo_type.set("FULL")

        ctk.CTkButton(wrap, text="Chạy backup", command=self._run_manual_backup)\
            .grid(row=1, column=2, padx=8, pady=6, sticky="w")

    # --------------------- Khối UI: Task Scheduler ---------------------

    def _build_task_scheduler(self, row: int):
        wrap = ctk.CTkFrame(self)
        wrap.grid(row=row, column=0, padx=16, pady=8, sticky="ew")
        wrap.grid_columnconfigure(1, weight=1)
        wrap.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(wrap, text="Task Scheduler (Windows)", font=ctk.CTkFont(weight="bold"))\
            .grid(row=0, column=0, padx=12, pady=(10, 6), sticky="w")

        # Thông số chính
        ctk.CTkLabel(wrap, text="SQL Instance:").grid(row=1, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_instance = ctk.CTkEntry(wrap, width=240); self.ent_instance.grid(row=1, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Số strips (file):").grid(row=1, column=2, padx=(12, 8), pady=6, sticky="e")
        self.spn_stripes = ctk.CTkEntry(wrap, width=80); self.spn_stripes.grid(row=1, column=3, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Lưu script powershell vào:").grid(row=2, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_ps1 = ctk.CTkEntry(wrap, width=420, placeholder_text=r"VD: C:\Scripts\Backup-Db.ps1")
        self.ent_ps1.grid(row=2, column=1, columnspan=2, padx=8, pady=6, sticky="w")
        ctk.CTkButton(wrap, text="Thay đổi vị trí lưu", command=self._choose_ps1_path).grid(row=2, column=3, padx=8, pady=6, sticky="w")

        # Run whether user... (mặc định True, không cho tắt để đáp ứng yêu cầu)
        self.chk_run_always_var = ctk.BooleanVar(value=True)
        cb = ctk.CTkCheckBox(
            wrap,
            text="Run whether user is logged on or not (chạy nền, cần User/Password)",
            variable=self.chk_run_always_var
        )
        cb.grid(row=3, column=0, columnspan=2, padx=8, pady=(0, 8), sticky="w")
        cb.configure(state="disabled")  # Không cho tắt 

        # User/Pass của Windows (bắt buộc khi dùng run whether...)
        ctk.CTkLabel(wrap, text="User (DOMAIN\\User hoặc User):").grid(row=4, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_user = ctk.CTkEntry(wrap, width=240); self.ent_user.grid(row=4, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="Password:").grid(row=4, column=2, padx=(12, 8), pady=6, sticky="e")
        self.ent_pass = ctk.CTkEntry(wrap, width=180, show="*"); self.ent_pass.grid(row=4, column=3, padx=8, pady=6, sticky="w")

        # SQL Auth (tuỳ chọn) – dùng khi tài khoản Windows KHÔNG có quyền trên SQL
        ctk.CTkLabel(wrap, text="SQL User (khi tài khoản windows ko có quyền đăng nhập SQL Server):").grid(row=5, column=0, padx=(12, 8), pady=6, sticky="e")
        self.ent_sql_user = ctk.CTkEntry(wrap, width=240); self.ent_sql_user.grid(row=5, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(wrap, text="SQL Pass:").grid(row=5, column=2, padx=(12, 8), pady=6, sticky="e")
        self.ent_sql_pass = ctk.CTkEntry(wrap, width=180, show="*"); self.ent_sql_pass.grid(row=5, column=3, padx=8, pady=6, sticky="w")

        # Nút thao tác
        rowb = 6
        ctk.CTkButton(wrap, text="✍️ Tạo file script", command=self._generate_ps1)\
            .grid(row=rowb, column=1, padx=8, pady=(8, 8), sticky="w")
        ctk.CTkButton(wrap, text="🔍 Kiểm tra task", command=self._check_tasks)\
            .grid(row=rowb, column=2, padx=8, pady=(8, 8), sticky="w")
        ctk.CTkButton(wrap, text="📋 Hiển thị lệnh tạo (copy chạy Admin)", command=self._show_commands)\
            .grid(row=rowb, column=3, padx=8, pady=(8, 8), sticky="w")

        ctk.CTkButton(wrap, text="🛡️ Tạo schtasks (yêu cầu quyền Admin)", command=self._create_tasks_elevated)\
            .grid(row=rowb+1, column=1, padx=8, pady=(0, 8), sticky="w")
        ctk.CTkButton(wrap, text="🗑️ Xóa task (yêu cầu quyền Admin)", command=self._delete_tasks_elevated)\
            .grid(row=rowb+1, column=2, padx=8, pady=(0, 8), sticky="w")

    # ============================ DB selection ============================

    def _init_db_selection(self):
        values = sorted(list(self.owner.selected_databases)) if hasattr(self.owner, "selected_databases") else []
        if values and not self.cbo_db.get():
            self.cbo_db.set(values[0])
        self._on_change_db()

    def _reload_db_list(self):
        values = sorted(list(self.owner.selected_databases)) if hasattr(self.owner, "selected_databases") else []
        self.cbo_db.configure(values=values)
        if values:
            if self.cbo_db.get() not in values:
                self.cbo_db.set(values[0])
            self._on_change_db()
        else:
            self.cbo_db.set(""); self.current_db = None; self._clear_form()

    def _on_change_db(self):
        """Nạp cấu hình đã lưu cho DB hiện tại (nếu có)."""
        self.current_db = self.cbo_db.get().strip() or None
        if not self.current_db:
            self._clear_form(); return

        per_db = self.owner.config.setdefault("per_db", {})
        db_cfg: Dict[str, Any] = per_db.setdefault(self.current_db, {})
        db_cfg.setdefault("backup_dir", None)
        db_cfg.setdefault("schedule", {"full": "0 0 * * 0", "diff": "30 0 * * 1-6", "log": "*/15 * * * *"})
        db_cfg.setdefault("scheduler", {
            "instance": ".\\SQLEXPRESS", "stripes": 2, "ps1_path": "C:\\Scripts\\Backup-Db.ps1",
            "run_always": True, "user": "", "pass": "", "sql_user": "", "sql_pass": ""
        })

        # Storage
        self.ent_dir.delete(0, "end")
        if db_cfg.get("backup_dir"):
            self.ent_dir.insert(0, db_cfg["backup_dir"])

        # Schedule
        sch = db_cfg.get("schedule", {})
        self.ent_full.delete(0, "end"); self.ent_full.insert(0, sch.get("full", "0 0 * * 0"))
        self.ent_diff.delete(0, "end"); self.ent_diff.insert(0, sch.get("diff", "30 0 * * 1-6"))
        self.ent_log.delete(0, "end");  self.ent_log.insert(0,  sch.get("log",  "*/15 * * * *"))

        # Scheduler
        s2 = db_cfg.get("scheduler", {})
        self.ent_instance.delete(0, "end"); self.ent_instance.insert(0, s2.get("instance", ".\\SQLEXPRESS"))
        self.spn_stripes.delete(0, "end");   self.spn_stripes.insert(0, str(s2.get("stripes", 2)))
        self.ent_ps1.delete(0, "end");       self.ent_ps1.insert(0, s2.get("ps1_path", "C:\\Scripts\\Backup-Db.ps1"))

        # 'Run whether...' mặc định True và bị khoá (đã set ở UI)
        self.chk_run_always_var.set(True)

        # RU/RP bắt buộc
        self.ent_user.delete(0, "end"); self.ent_user.insert(0, s2.get("user", ""))
        self.ent_pass.delete(0, "end"); self.ent_pass.insert(0, s2.get("pass", ""))

        # SQL Auth (tuỳ chọn)
        self.ent_sql_user.delete(0, "end"); self.ent_sql_user.insert(0, s2.get("sql_user", ""))
        self.ent_sql_pass.delete(0, "end"); self.ent_sql_pass.insert(0, s2.get("sql_pass", ""))

    def _clear_form(self):
        """Xoá nội dung UI khi chưa có DB."""
        self.ent_dir.delete(0, "end")
        self.ent_full.delete(0, "end"); self.ent_diff.delete(0, "end"); self.ent_log.delete(0, "end")
        self.ent_instance.delete(0, "end"); self.spn_stripes.delete(0, "end"); self.ent_ps1.delete(0, "end")
        self.chk_run_always_var.set(True)
        self.ent_user.delete(0, "end"); self.ent_pass.delete(0, "end")
        self.ent_sql_user.delete(0, "end"); self.ent_sql_pass.delete(0, "end")

    def _persist_for_current_db(self):
        """Lưu thư mục đích cho DB hiện tại khi người dùng nhập xong."""
        if not self.current_db: return
        path = self.ent_dir.get().strip() or None
        self.owner.config.setdefault("per_db", {}).setdefault(self.current_db, {})["backup_dir"] = path
        self.owner.save_config(silent=True)
        self._log(f"• Đã lưu thư mục lưu trữ cho [{self.current_db}]")

    # ============================ Storage actions ============================

    def _choose_local_dir(self):
        """Chọn thư mục cục bộ (máy đang chạy UI). LƯU Ý: SQL Server service mới là bên ghi file."""
        path = filedialog.askdirectory(title="Chọn thư mục (cục bộ)")
        if path:
            if not path.endswith(os.sep): path += os.sep
            self.ent_dir.delete(0, "end"); self.ent_dir.insert(0, path)
            self._persist_for_current_db()

    def _test_write_perm_model(self):
        """
        Kiểm tra quyền ghi của SQL Server vào thư mục đích bằng cách backup DB 'model' (nhẹ).
        - Không phụ thuộc DB đang chọn (tránh gây tải trên DB lớn).
        - Dùng COPY_ONLY để file nhỏ, không ảnh hưởng chuỗi backup chính.
        - Có thử xp_dirtree để 'nhìn' thư mục (không quyết định quyền ghi).
        - Thử xoá file test bằng xp_cmdshell (nếu tắt thì bỏ qua, chỉ log).
        """
        # 1) Kiểm tra đầu vào/các điều kiện cần
        if not self.owner or not getattr(self.owner, "conn", None):
            messagebox.showwarning("Chưa kết nối", "Kết nối SQL Server trước khi kiểm tra.")
            return

        # Lấy thư mục đích từ UI (trên MÁY CHẠY SQL, không phải máy UI)
        target_dir = self.ent_dir.get().strip()
        if not target_dir:
            messagebox.showwarning("Thiếu thông tin", "Nhập thư mục đích backup (ví dụ: E:\\SQL_Backup\\ hoặc \\\\server\\share\\path\\).")
            return

        # Hiển thị log gọn (xoá log cũ)
        self._clear_status()
        self._log("=== KIỂM TRA QUYỀN GHI BẰNG DB 'model' (nhẹ) ===")

        # 2) Chạy trong thread để UI không đơ
        def _work():
            conn = self.owner.conn
            cur = None
            # Lưu trạng thái autocommit hiện tại để khôi phục sau
            prev_autocommit = getattr(conn, "autocommit", False)
            try:
                conn.autocommit = True  # Backup/maintenance nên bật Autocommit
                cur = conn.cursor()

                # Chuẩn hoá đường dẫn: kết thúc bằng "\" nếu là path cục bộ
                base = target_dir
                if not (base.endswith("\\") or base.endswith("/")):
                    base += "\\"

                # 2.1) Thử 'nhìn' thư mục bằng xp_dirtree (có thể bị tắt — chỉ cảnh báo)
                try:
                    cur.execute("EXEC master..xp_dirtree ?, 1, 1", (base,))
                    self._log(f"[OK] xp_dirtree nhìn thấy thư mục: {base}")
                except Exception as e:
                    self._log(f"[CHÚ Ý] xp_dirtree lỗi (bỏ qua bước này): {e}")

                # 2.2) Sinh đường dẫn file test (tên có PID để tránh trùng)
                import os as _os, time as _time
                test_name = f"model_PERM_TEST_{_os.getpid()}_{int(_time.time())}.bak"
                test_path = base + test_name

                # 2.3) Backup DB 'model' → file test (nhanh, nhỏ)
                # COPY_ONLY: không ghi nhận vào chuỗi full/diff hiện hữu
                # COMPRESSION: giảm I/O đĩa và mạng (nếu UNC)
                # INIT, SKIP, CHECKSUM: an toàn & rõ ràng
                self._log(f"→ Tạo file test: {test_path}")
                cur.execute(
                    """
                    BACKUP DATABASE [model]
                    TO DISK = ?
                    WITH COPY_ONLY, INIT, SKIP, CHECKSUM, STATS = 1;
                    """,
                    (test_path,)
                )
                self._log("[OK] ĐÃ GHI file backup test bằng DB 'model'.")

                # 2.4) Thử xoá file test (nếu xp_cmdshell bật)
                try:
                    # Lưu ý escape dấu " trong đường dẫn khi đưa vào lệnh del
                    del_cmd = f'del "{test_path.replace("\"", "\"\"")}"'
                    cur.execute("EXEC master..xp_cmdshell ?", (del_cmd,))
                    self._log("[OK] Đã xoá file test bằng xp_cmdshell.")
                except Exception:
                    # Không sao nếu xp_cmdshell tắt — chỉ nhắc admin xoá tay
                    self._log("[CHÚ Ý] xp_cmdshell tắt/không xoá được. Hãy xoá tay file test nếu cần.")

                self._log("[KẾT LUẬN] SQL Server CÓ thể ghi vào thư mục (test bằng 'model').")

            except Exception as e:
                # Ghi lỗi tổng quát
                self._log(f"[THẤT BẠI] Không xác minh được quyền ghi bằng 'model': {e}")
            finally:
                # Khôi phục autocommit
                try:
                    conn.autocommit = prev_autocommit
                except Exception:
                    pass
                # Đóng cursor nếu còn
                try:
                    if cur is not None:
                        cur.close()
                except Exception:
                    pass

        threading.Thread(target=_work, daemon=True).start()

    # ============================= Schedule (CRON) =============================

    def _save_schedule(self):
        """Lưu 3 dòng CRON (tham khảo) – phục vụ biến sang schtasks."""
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Chọn CSDL trước."); return
        full = self.ent_full.get().strip()
        diff = self.ent_diff.get().strip()
        log  = self.ent_log.get().strip()
        for s, nm in ((full,"FULL"),(diff,"DIFF"),(log,"LOG")):
            if not _CRON_RE.match(s or ""):
                messagebox.showwarning("CRON không hợp lệ", f"Lịch {nm} chưa đúng định dạng (5 trường)."); return
        db_cfg = self.owner.config.setdefault("per_db", {}).setdefault(self.current_db, {})
        db_cfg.setdefault("schedule", {})["full"] = full
        db_cfg["schedule"]["diff"] = diff
        db_cfg["schedule"]["log"]  = log
        self.owner.save_config(silent=True)
        messagebox.showinfo("Đã lưu", f"Đã lưu lịch (tham khảo) cho [{self.current_db}].")

    # ============================== Manual backup ==============================

    def _run_manual_backup(self):
        """Chạy BACKUP trực tiếp (FULL/DIFF/LOG) – tiện kiểm tra nhanh."""
        if not self.owner.conn:
            messagebox.showwarning("Chưa kết nối", "Kết nối SQL Server trước."); return
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Chọn CSDL trước khi backup."); return

        per_db = self.owner.config.get("per_db", {})
        bdir = per_db.get(self.current_db, {}).get("backup_dir")
        if not bdir:
            messagebox.showwarning("Thiếu thông tin", "Chưa có thư mục lưu trữ cho CSDL này."); return

        btype = self.cbo_type.get().strip().upper()
        self._clear_status()

        def _work():
            try:
                conn = self.owner.conn
                restore_autocommit = getattr(conn, "autocommit", False)
                conn.autocommit = True
                cur = conn.cursor()
                ts = getattr(self.owner, "timestamp_str", lambda: "YYYYMMDD_HHMMSS")()

                if btype == "LOG":
                    target = f"{bdir}{self.current_db}_LOG_{ts}.trn"
                    sql = f"BACKUP LOG [{self.current_db}] TO DISK = ? WITH INIT, SKIP, CHECKSUM, STATS=1"
                elif btype == "DIFF":
                    target = f"{bdir}{self.current_db}_DIFF_{ts}.dif"
                    sql = f"BACKUP DATABASE [{self.current_db}] TO DISK = ? WITH DIFFERENTIAL, INIT, SKIP, CHECKSUM, STATS=1"
                else:
                    target = f"{bdir}{self.current_db}_FULL_{ts}.bak"
                    sql = f"BACKUP DATABASE [{self.current_db}] TO DISK = ? WITH INIT, SKIP, CHECKSUM, STATS=1"

                self._log(f"→ [{self.current_db}] [{btype}] => {target}")
                cur.execute(sql, (target,))
                self._log("   ✓ Hoàn tất.")
            except Exception as e:
                self._log(f"[LỖI] {e}")
            finally:
                try: conn.autocommit = restore_autocommit
                except Exception: pass

        threading.Thread(target=_work, daemon=True).start()

    # ============================ Task Scheduler ============================

    def _choose_ps1_path(self):
        """Chọn nơi lưu script PS1."""
        path = filedialog.asksaveasfilename(
            title="Lưu file PowerShell", defaultextension=".ps1",
            filetypes=[("PowerShell Script", "*.ps1"), ("All Files", "*.*")]
        )
        if path:
            self.ent_ps1.delete(0, "end"); self.ent_ps1.insert(0, path)
            self._persist_scheduler_fields()

    def _persist_scheduler_fields(self):
        """Lưu các trường Task Scheduler vào config DB hiện tại."""
        if not self.current_db: return
        inst = self.ent_instance.get().strip() or ".\\SQLEXPRESS"
        try:
            stripes = int(self.spn_stripes.get().strip() or "1")
        except Exception:
            stripes = 1
        ps1 = self.ent_ps1.get().strip() or "C:\\Scripts\\Backup-Db.ps1"
        usr = self.ent_user.get().strip()
        pwd = self.ent_pass.get().strip()
        sql_user = self.ent_sql_user.get().strip()
        sql_pass = self.ent_sql_pass.get().strip()

        db_cfg = self.owner.config.setdefault("per_db", {}).setdefault(self.current_db, {})
        sch = db_cfg.setdefault("scheduler", {})
        sch["instance"] = inst
        sch["stripes"]  = stripes
        sch["ps1_path"] = ps1
        sch["run_always"] = True  # cố định theo yêu cầu
        sch["user"] = usr
        sch["pass"] = pwd
        sch["sql_user"] = sql_user
        sch["sql_pass"] = sql_pass
        self.owner.save_config(silent=True)

    def _generate_ps1(self):
        """
        Sinh script PowerShell:
        - Có ghi log (BasePath\\_TaskLogs\\DB.log)
        - Hỗ trợ SqlUser/SqlPass (nếu tài khoản Windows không có quyền SQL)
        - Xử lý lỗi: ghi FAIL vào log và ném ngoại lệ (để Task thấy LastRun != 0)
        """
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Chọn CSDL trước."); return

        per_db = self.owner.config.get("per_db", {})
        bdir = per_db.get(self.current_db, {}).get("backup_dir")
        if not bdir:
            messagebox.showwarning("Thiếu thông tin", "Chưa có thư mục lưu trữ cho CSDL này."); return

        inst = self.ent_instance.get().strip() or ".\\SQLEXPRESS"
        try:
            stripes = int(self.spn_stripes.get().strip() or "1")
        except Exception:
            stripes = 1

        ps1_path = self.ent_ps1.get().strip() or "C:\\Scripts\\Backup-Db.ps1"

        # LogPath: <BasePath>\_TaskLogs\<DB>.log
        log_dir = os.path.join(bdir.rstrip("\\/"), "_TaskLogs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{self.current_db}.log")

        self._persist_scheduler_fields()

        # Script PS1 (SqlUser/SqlPass tuỳ chọn)
        ps1_content = f"""param(
  [Parameter(Mandatory=$true)] [string]$Instance,
  [Parameter(Mandatory=$true)] [string]$Database,
  [Parameter(Mandatory=$true)] [string]$BasePath,
  [Parameter(Mandatory=$true)] [ValidateSet("Full","Diff","Log")] [string]$Type,
  [Parameter(Mandatory=$true)] [int]$Stripes,
  [Parameter(Mandatory=$true)] [string]$LogPath,
  [Parameter(Mandatory=$false)] [string]$SqlUser,
  [Parameter(Mandatory=$false)] [string]$SqlPass
)

$ErrorActionPreference = "Stop"

function Write-Log($ok, $targets) {{
  try {{
    $ts = (Get-Date).ToString("s")
    $status = if ($ok) {{ "OK" }} else {{ "FAIL" }}
    $files = ($targets -join ";")
    "$ts|$Database|$Type|$status|$files" | Add-Content -LiteralPath $LogPath -Encoding UTF8
  }} catch {{ }}
}}

# 1) Tạo thư mục đích theo ngày
$day = Get-Date -Format "yyyyMMdd"
$dir = Join-Path $BasePath (Join-Path $Database (Join-Path $Type $day))
New-Item -ItemType Directory -Force -Path $dir | Out-Null

# 2) Danh sách file striped
$time   = Get-Date -Format "HHmmss"
$ext    = if ($Type -eq "Log") {{ "trn" }} elseif ($Type -eq "Diff") {{ "dif" }} else {{ "bak" }}
$targets = @()
for ($i=1; $i -le $Stripes; $i++) {{
  $targets += (Join-Path $dir ("{self.current_db}_$($Type.ToUpper())_${{time}}_$i.$ext"))
}}
$disks = ($targets | ForEach-Object {{ "DISK = N'" + $_.Replace("'", "''") + "'" }}) -join ", "

# 3) Chọn chuỗi T-SQL theo Type
if ($Type -eq "Full") {{
  $tsql = @"
IF SERVERPROPERTY('EngineEdition') <> 4
BEGIN
  BACKUP DATABASE [{self.current_db}]
  TO $disks
  WITH COMPRESSION, CHECKSUM, STATS = 5;
END
ELSE
BEGIN
  BACKUP DATABASE [{self.current_db}]
  TO $disks
  WITH CHECKSUM, STATS = 5;
END;
RESTORE VERIFYONLY FROM $disks WITH CHECKSUM;
"@
}}
elseif ($Type -eq "Diff") {{
  $tsql = @"
BACKUP DATABASE [{self.current_db}]
TO $disks
WITH DIFFERENTIAL, CHECKSUM, STATS = 5;
"@
}}
else {{
  $tsql = @"
IF EXISTS (
  SELECT 1
  FROM sys.dm_exec_requests
  WHERE command IN ('BACKUP DATABASE','BACKUP LOG')
    AND database_id = DB_ID(N'{self.current_db}')
)
BEGIN
  PRINT 'Backup in progress. Skipping LOG backup.';
  RETURN;
END;

BACKUP LOG [{self.current_db}]
TO $disks
WITH CHECKSUM, STATS = 5;
"@
}}

# 4) Gọi sqlcmd: ưu tiên SQL Auth nếu có, nếu không dùng -E
try {{
  if ([string]::IsNullOrWhiteSpace($SqlUser) -or [string]::IsNullOrWhiteSpace($SqlPass)) {{
    & sqlcmd -S $Instance -d master -E -b -Q $tsql
  }} else {{
    & sqlcmd -S $Instance -d master -U $SqlUser -P $SqlPass -b -Q $tsql
  }}
  if ($LASTEXITCODE -ne 0) {{ throw "Backup failed with exit code $LASTEXITCODE" }}
  Write-Log $true $targets
}}
catch {{
  Write-Log $false $targets
  throw
}}
"""
        try:
            os.makedirs(os.path.dirname(ps1_path), exist_ok=True)
            with open(ps1_path, "w", encoding="utf-8") as f:
                f.write(ps1_content)
            self._log(f"[OK] Đã ghi PS1: {ps1_path}\n• Log: {log_path}\n• Hỗ trợ SqlUser/SqlPass (nếu cần).")
            messagebox.showinfo("Tạo PS1", f"Đã tạo script:\n{ps1_path}\nScript hỗ trợ SQL Auth tuỳ chọn.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không lưu được PS1: {e}")

    def _task_names(self) -> Dict[str, str]:
        """Tên 3 task chuẩn hoá theo DB."""
        db = self.current_db or "DB"
        return {"FULL": f"BK_FULL_{db}", "DIFF": f"BK_DIFF_{db}", "LOG": f"BK_LOG_{db}"}

    def _build_one_cmd(self, task_name: str, cron_expr: str, task_type: str,
                       ps_base_exec: str, user: str, pwd: str) -> str:
        """
        Sinh lệnh schtasks cho 1 Task:
          - BẮT BUỘC /RU /RP (Run whether user is logged on or not)
          - /RL HIGHEST, KHÔNG dùng /IT (để chạy nền, không mở console)
        """
        if not user or not pwd:
            raise ValueError("Cần nhập User/Password (Windows) để tạo task chạy nền.")

        args = cron_to_schtasks_args(cron_expr)
        base = f'schtasks /Create /TN "{task_name}" /RL HIGHEST /F /RU "{user}" /RP "{pwd}" '

        if args["type"] == "MINUTE":
            return (base + f'/SC MINUTE /MO {args["mo"]} /ST {args["st"]} /DU {args["du"]} '
                    + f'/TR "{ps_base_exec} -Type {task_type}"')

        if args["type"] == "DAILY":
            return (base + f'/SC DAILY /ST {args["st"]} '
                    + f'/TR "{ps_base_exec} -Type {task_type}"')

        if args["type"] == "WEEKLY":
            dlist = args.get("dlist", "")
            if not dlist:
                raise ValueError("CRON tuần cần danh sách thứ (MON,TUE,...).")
            return (base + f'/SC WEEKLY /D {dlist} /ST {args["st"]} '
                    + f'/TR "{ps_base_exec} -Type {task_type}"')

        if args["type"] == "MONTHLY":
            dom = args.get("dom", "")
            return (base + f'/SC MONTHLY /D {dom} /ST {args["st"]} '
                    + f'/TR "{ps_base_exec} -Type {task_type}"')

        raise ValueError("Không hỗ trợ loại CRON này.")

    def _build_schtasks_cmds(self) -> Optional[Dict[str, str]]:
        """
        Kết hợp mọi dữ liệu hiện tại thành 3 lệnh schtasks.
        - Kiểm tra PS1 tồn tại trước
        - Bắt buộc có User/Pass
        - Gắn SqlUser/SqlPass vào /TR nếu có
        """
        if not self.current_db:
            messagebox.showwarning("Chưa chọn CSDL", "Chọn CSDL trước."); return None

        per_db = self.owner.config.get("per_db", {})
        db_cfg = per_db.get(self.current_db, {})
        bdir = db_cfg.get("backup_dir")
        if not bdir:
            messagebox.showwarning("Thiếu thông tin", "Chưa có thư mục lưu trữ cho CSDL này."); return None

        schd = db_cfg.get("schedule", {})
        cron_full = schd.get("full", "")
        cron_diff = schd.get("diff", "")
        cron_log  = schd.get("log",  "")

        sch2 = db_cfg.get("scheduler", {})
        inst = (sch2.get("instance") or self.ent_instance.get().strip() or ".\\SQLEXPRESS").replace('"','\\"')
        try:
            stripes = int(str(sch2.get("stripes", self.spn_stripes.get().strip() or "1")))
        except Exception:
            stripes = 1
        ps1_path_in = (sch2.get("ps1_path") or self.ent_ps1.get().strip() or "C:\\Scripts\\Backup-Db.ps1")
        user = sch2.get("user") or self.ent_user.get().strip()
        pwd  = sch2.get("pass") or self.ent_pass.get().strip()
        sql_user = (sch2.get("sql_user") or self.ent_sql_user.get().strip() or "")
        sql_pass = (sch2.get("sql_pass") or self.ent_sql_pass.get().strip() or "")

        if not os.path.isfile(ps1_path_in):
            messagebox.showerror("Thiếu script PS1", f"Không tìm thấy file PS1:\n{ps1_path_in}\nHãy tạo bằng '✍️ Tạo file PS1' trước.")
            return None

        # LogPath mặc định
        log_dir = os.path.join(bdir.rstrip("\\/"), "_TaskLogs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, f"{self.current_db}.log")

        # Chuỗi /TR: PowerShell chạy ẩn (không popup nếu là 'Run whether...' + /RL Highest)
        dbn  = self.current_db.replace('"','\\"')
        base = bdir.rstrip("\\/").replace('"','\\"')
        ps1  = ps1_path_in.replace('"','\\"')

        ps_exec = (f'powershell.exe -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass '
                   f'-File "{ps1}" -Instance "{inst}" -Database "{dbn}" -BasePath "{base}" '
                   f'-Stripes {stripes} -LogPath "{log_path}"')

        # Nếu có SQL Auth → gắn kèm để đảm bảo quyền trên SQL
        # if sql_user and sql_pass:
        #     ps_exec += f' -SqlUser "{sql_user.replace(\'"\', \'\\\"\')}" -SqlPass "{sql_pass.replace(\'"\', \'\\\"\')}"'

        names = self._task_names()
        cmds: Dict[str, str] = {}
        try:
            cmds[names["FULL"]] = self._build_one_cmd(names["FULL"], cron_full, "Full", ps_exec, user, pwd)
            cmds[names["DIFF"]] = self._build_one_cmd(names["DIFF"], cron_diff, "Diff", ps_exec, user, pwd)
            cmds[names["LOG"]]  = self._build_one_cmd(names["LOG"],  cron_log,  "Log",  ps_exec, user, pwd)
        except ValueError as e:
            messagebox.showerror("CRON/Thông tin chưa hợp lệ", str(e)); return None

        self._persist_scheduler_fields()
        return cmds
        
    def _task_exists(self, task_name: str) -> bool:
        try:
            proc = subprocess.run(['schtasks','/Query','/TN',task_name], capture_output=True, text=True, shell=False)
            return proc.returncode == 0
        except Exception as e:
            self._log(f"[LỖI] Query task {task_name}: {e}")
            return False

    def _check_tasks(self):
        names = self._task_names()
        self._clear_status()
        self._log("=== Kiểm tra Task Scheduler ===")
        for label, tname in [("FULL", names["FULL"]), ("DIFF", names["DIFF"]), ("LOG", names["LOG"])]:
            exists = self._task_exists(tname)
            self._log(f"{label}: {tname} -> {'ĐÃ TỒN TẠI' if exists else 'CHƯA CÓ'}")
        messagebox.showinfo("Kiểm tra task", "Đã hoàn tất quá trình kiểm tra.\nXem kết quả trong khung trạng thái bên dưới.")

    def _create_tasks_elevated(self):
        """
        Tạo 3 task bằng schtasks:
        - Gộp lệnh vào 1 .cmd tạm
        - Mở cmd.exe 'Run as Administrator' để thực thi (UAC)
        - Dùng /RU /RP (bắt buộc), /RL HIGHEST, KHÔNG /IT
        """
        cmds = self._build_schtasks_cmds()
        if not cmds: return
        try:
            with tempfile.NamedTemporaryFile(prefix="create_tasks_", suffix=".cmd", delete=False, mode="w", encoding="utf-8") as tf:
                batch_path = tf.name
                tf.write("@echo on\r\n")
                for _, cmd in cmds.items():
                    tf.write(cmd + "\r\n")
                tf.write("echo.\r\n")
                tf.write("echo ===== Done. Press any key to close... =====\r\n")
                tf.write("pause > nul\r\n")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không tạo được file batch: {e}"); return

        try:
            self._log(f"→ Mở Administrator và tạo task bằng: {batch_path}")
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c "{batch_path}"', None, 1)
            if rc <= 32:
                messagebox.showerror("Không thể nâng quyền", f"Mã lỗi ShellExecute: {rc}\nHãy chạy tay file:\n{batch_path}")
            else:
                messagebox.showinfo("Đang tạo task", "Cửa sổ Administrator đã mở để tạo task.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể chạy nâng quyền: {e}\nHãy chạy tay file:\n{batch_path}")

    def _delete_tasks_elevated(self):
        """Xoá 3 task tương ứng DB hiện tại (nâng quyền Admin)."""
        names = self._task_names()
        try:
            with tempfile.NamedTemporaryFile(prefix="delete_tasks_", suffix=".cmd", delete=False, mode="w", encoding="utf-8") as tf:
                batch_path = tf.name
                tf.write("@echo on\r\n")
                for tname in [names["FULL"], names["DIFF"], names["LOG"]]:
                    tf.write(f'schtasks /Delete /TN "{tname}" /F\r\n')
                tf.write("echo.\r\n")
                tf.write("echo ===== Done. Press any key to close... =====\r\n")
                tf.write("pause > nul\r\n")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không tạo được file batch: {e}"); return

        try:
            self._log(f"→ Mở Administrator và xoá task bằng: {batch_path}")
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", f'/c "{batch_path}"', None, 1)
            if rc <= 32:
                messagebox.showerror("Không thể nâng quyền", f"Mã lỗi ShellExecute: {rc}\nHãy chạy tay file:\n{batch_path}")
            else:
                messagebox.showinfo("Đang xoá task", "Cửa sổ Administrator đã mở để xoá task.")
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể chạy nâng quyền: {e}\nHãy chạy tay file:\n{batch_path}")

    def _show_commands(self):
        """Hiển thị các lệnh schtasks để copy (tự chạy trong CMD/Powershell Admin)."""
        cmds = self._build_schtasks_cmds()
        if not cmds: return
        self._clear_status()
        self._log("=== Lệnh schtasks (copy & chạy trong PowerShell/Command Prompt Run as Administrator) ===")
        for name, cmd in cmds.items():
            self._log(f"\n# {name}\n{cmd}")
        messagebox.showinfo("Lệnh đã sẵn sàng",
                            "Các lệnh đã hiển thị trong ô trạng thái phía dưới.\n"
                            "Hãy mở PowerShell/Command Prompt 'Run as Administrator' và copy chạy.")

    # ================================ Utils ================================

    def _log(self, s: str):
        """Ghi 1 dòng vào khung trạng thái."""
        self.status_box.configure(state="normal")
        self.status_box.insert("end", s + "\n")
        self.status_box.see("end")
        self.status_box.configure(state="disabled")

    def _clear_status(self):
        """Xoá toàn bộ khung trạng thái."""
        self.status_box.configure(state="normal")
        self.status_box.delete("1.0", "end")
        self.status_box.configure(state="disabled")