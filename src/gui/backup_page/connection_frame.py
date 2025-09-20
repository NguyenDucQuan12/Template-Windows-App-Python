"""
ConnectionFrame
- Chọn ODBC Driver + chế độ đăng nhập (SQL/Windows)
- Kết nối SQL Server (pyodbc), hiển thị danh sách DB (sys.databases)
- Thêm DB được chọn vào danh sách backup (lưu tại DatabasePage.state)
- Lưu cấu hình kết nối vào JSON (thông qua DatabasePage._save_config())
"""
import customtkinter as ctk
from tkinter import ttk, messagebox
import threading
import logging
from typing import Optional, Dict, Any
import pyodbc

from utils.utils import get_odbc_drivers_for_sql_server

logger = logging.getLogger(__name__)

# ----------------- helpers -----------------

def _build_conn_str(driver: str, server: str, auth_mode: str, user: Optional[str], pwd: Optional[str], timeout: int = 8) -> str:

    if auth_mode != "sql":
        return (
            f"DRIVER={driver};"
            f"SERVER={server};"
            "DATABASE=master;"
            "Trusted_Connection=Yes;"
            "TrustServerCertificate=yes;"
            f"Connection Timeout={timeout};"
        )
    else:
        return (
            f"DRIVER={driver};"
            f"SERVER={server};"
            "DATABASE=master;"
            f"UID={user};PWD={pwd};"
            "TrustServerCertificate=yes;"
            f"Connection Timeout={timeout};"
        )

class ConnectionFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page  # DatabasePage
        self.conn: Optional[pyodbc.Connection] = None
        self.conn_info: Dict[str, Any] = {}

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Kết nối SQL Server", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        # Form bên trái
        form = ctk.CTkFrame(self)
        form.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        form.grid_columnconfigure(1, weight=1)

        # Driver
        ctk.CTkLabel(form, text="ODBC Driver:").grid(row=0, column=0, padx=(12,8), pady=6, sticky="w")
        drivers = self.owner.odbc_drivers or get_odbc_drivers_for_sql_server()
        self.cbo_driver = ctk.CTkComboBox(form, values=drivers, width=260)
        self.cbo_driver.grid(row=0, column=1, padx=8, pady=6, sticky="w")
        if drivers:
            # nếu có config cũ -> set theo config
            self.cbo_driver.set(self.owner.config["connection"].get("driver") or drivers[0])

        # Server
        ctk.CTkLabel(form, text="Server/Instance:").grid(row=1, column=0, padx=(12,8), pady=6, sticky="w")
        self.ent_server = ctk.CTkEntry(form, width=260, placeholder_text="HOST\\INSTANCE hoặc 10.0.0.5,1433")
        self.ent_server.grid(row=1, column=1, padx=8, pady=6, sticky="w")
        if self.owner.config["connection"].get("server"):
            self.ent_server.insert(0, self.owner.config["connection"]["server"])

        # Auth mode
        ctk.CTkLabel(form, text="Chế độ đăng nhập:").grid(row=2, column=0, padx=(12,8), pady=6, sticky="w")
        self.auth_mode = ctk.StringVar(value=self.owner.config["connection"].get("auth_mode","sql"))
        auth = ctk.CTkFrame(form, fg_color="transparent")
        auth.grid(row=2, column=1, padx=8, pady=6, sticky="w")
        ctk.CTkRadioButton(auth, text="SQL Server (sa/…)", variable=self.auth_mode, value="sql", command=self._toggle_auth).pack(side="left", padx=(0,12))
        ctk.CTkRadioButton(auth, text="Windows", variable=self.auth_mode, value="windows", command=self._toggle_auth).pack(side="left")

        # User/Pass
        ctk.CTkLabel(form, text="Username:").grid(row=3, column=0, padx=(12,8), pady=6, sticky="w")
        self.ent_user = ctk.CTkEntry(form, width=260, placeholder_text="sa hoặc user SQL")
        self.ent_user.grid(row=3, column=1, padx=8, pady=6, sticky="w")
        if self.owner.config["connection"].get("username"):
            self.ent_user.insert(0, self.owner.config["connection"]["username"])

        ctk.CTkLabel(form, text="Password:").grid(row=4, column=0, padx=(12,8), pady=6, sticky="w")
        self.ent_pass = ctk.CTkEntry(form, width=260, placeholder_text="••••••••", show="*")
        self.ent_pass.grid(row=4, column=1, padx=8, pady=6, sticky="w")

        self.btn_connect = ctk.CTkButton(form, text="Kết nối", command=self._do_connect)
        self.btn_connect.grid(row=5, column=0, columnspan=2, padx=8, pady=(10,6), sticky="ew")

        self.lbl_status = ctk.CTkLabel(form, text="Chưa kết nối", text_color="#f59e0b")
        self.lbl_status.grid(row=6, column=0, columnspan=2, padx=8, pady=(4,12), sticky="w")

        # Khu danh sách DB bên phải
        right = ctk.CTkFrame(self)
        right.grid(row=1, column=1, padx=(0,16), pady=8, sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(right, text="Danh sách Database", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=12, pady=(12,8), sticky="w")
        self.tv = ttk.Treeview(right, columns=("name","state","recovery"), show="headings")
        for col, w in ("name",220),("state",120),("recovery",120):
            self.tv.heading(col, text=col.title())
            self.tv.column(col, width=w, anchor="w")
        self.tv.grid(row=1, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(right, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns")

        act = ctk.CTkFrame(right, fg_color="transparent")
        act.grid(row=2, column=0, padx=12, pady=8, sticky="ew")
        act.grid_columnconfigure(0, weight=1)
        act.grid_columnconfigure(1, weight=1)
        self.btn_refresh = ctk.CTkButton(act, text="↻ Nạp lại", command=self._refresh_dbs, state="disabled")
        self.btn_add     = ctk.CTkButton(act, text="➕ Thêm vào danh sách backup", command=self._add_selected, state="disabled")
        self.btn_refresh.grid(row=0, column=0, padx=(0,6), sticky="ew")
        self.btn_add.grid(row=0, column=1, padx=(6,0), sticky="ew")

        self._toggle_auth()

    # ----------------- event handlers -----------------
    def _toggle_auth(self):
        mode = self.auth_mode.get()
        if mode == "windows":
            self.ent_user.configure(state="disabled")
            self.ent_pass.configure(state="disabled")
        else:
            self.ent_user.configure(state="normal")
            self.ent_pass.configure(state="normal")

    def _do_connect(self):
        driver = self.cbo_driver.get().strip()
        server = self.ent_server.get().strip()
        mode   = self.auth_mode.get()
        user   = self.ent_user.get().strip() if mode == "sql" else None
        pwd    = self.ent_pass.get().strip() if mode == "sql" else None

        if not driver:
            messagebox.showwarning("Thiếu thông tin", "Chọn ODBC Driver.")
            return
        if not server:
            messagebox.showwarning("Thiếu thông tin", "Nhập Server/Instance.")
            return
        if mode == "sql" and (not user or not pwd):
            messagebox.showwarning("Thiếu thông tin", "Nhập Username/Password cho SQL Auth.")
            return

        conn_str = _build_conn_str(driver, server, mode, user, pwd)
        self.lbl_status.configure(text="Đang kết nối...", text_color="#f59e0b")
        self.btn_connect.configure(state="disabled")

        def _connect():
            try:
                conn = pyodbc.connect(conn_str)
                self.conn = conn
                self.owner.conn = conn  # chia sẻ cho toàn trang
                # Lưu config kết nối (không lưu password rõ)
                self.owner.config["connection"].update({
                    "driver": driver,
                    "server": server,
                    "auth_mode": mode,
                    "username": user,
                })
                self.owner.save_config(silent = True)  # ghi file JSON

                self.lbl_status.configure(text="Đã kết nối", text_color="#22c55e")
                self.btn_refresh.configure(state="normal")
                self.btn_add.configure(state="normal")
                self._refresh_dbs()
            except Exception as e:
                logger.exception("Connect failed: %s", e)
                self.lbl_status.configure(text=f"Kết nối thất bại: {e}", text_color="#ef4444")
            finally:
                self.btn_connect.configure(state="normal")

        threading.Thread(target=_connect, daemon=True).start()

    def _refresh_dbs(self):
        if not self.conn:
            return
        self.btn_refresh.configure(state="disabled")
        self.tv.delete(*self.tv.get_children())

        def _load():
            try:
                cur = self.conn.cursor()
                cur.execute("""
                    SELECT name, state_desc, recovery_model_desc
                    FROM sys.databases
                    WHERE database_id > 4
                    ORDER BY name ASC
                """)
                for name, state, rm in cur.fetchall():
                    self.tv.insert("", "end", values=(name, state, rm))
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể lấy danh sách database:\n{e}")
            finally:
                self.btn_refresh.configure(state="normal")

        threading.Thread(target=_load, daemon=True).start()

    def _add_selected(self):
        items = self.tv.selection()
        if not items:
            messagebox.showinfo("Chưa chọn", "Chọn ít nhất một DB.")
            return
        added = []
        for iid in items:
            name = self.tv.item(iid, "values")[0]
            if self.owner.add_database_for_backup(name):
                added.append(name)
        if added:
            # cập nhật config và lưu
            self.owner.config["databases"] = sorted(self.owner.selected_databases)
            self.owner.save_config(silent = True)
            messagebox.showinfo("Đã thêm", "\n".join(added))
        else:
            messagebox.showinfo("Thông báo", "Các DB đã có trong danh sách.")