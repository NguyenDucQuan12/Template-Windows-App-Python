import customtkinter as ctk
from tkinter import ttk, messagebox
import threading
import logging
from typing import Optional, Dict, Any
import pyodbc

from utils.utils import get_odbc_drivers_for_sql_server
from utils.modal_loading import ModalLoadingPopup

logger = logging.getLogger(__name__)

# ----------------- helpers -----------------

def _build_conn_str(driver: str, server: str, auth_mode: str, user: Optional[str], pwd: Optional[str], timeout: int = 8) -> str:
    """
    Tạo chuỗi kết nối với 2 tùy chọn đăng nhập là sử dụng window hoặc tài khoản đăng nhập  
    """

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

        # Hiển thị nội dung trang lên frame: Parent
        super().__init__(parent)

        # Biến lưu dữ trạng thái của frame Database
        self.owner = owner_page 

        self.loading = ModalLoadingPopup(parent)  # truyền frame làm parent

        # Biến lưu giữ kết nối tới DB
        self.conn: Optional[pyodbc.Connection] = None
        self.conn_info: Dict[str, Any] = {}

        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(self, text="Kết nối SQL Server", font=ctk.CTkFont(size=18, weight="bold")).grid(row=0, column=0, padx=16, pady=(16,8), sticky="w")

        # Frame thông tin đăng nhập bên trái
        Login_Frame = ctk.CTkFrame(self)
        Login_Frame.grid(row=1, column=0, padx=16, pady=8, sticky="nsew")
        Login_Frame.grid_columnconfigure(1, weight=1)
        Login_Frame.grid_rowconfigure(6, weight=1)

        # Driver
        ctk.CTkLabel(Login_Frame, text="ODBC Driver:").grid(row=0, column=0, padx=(12,8), pady=6, sticky="w")
        drivers = get_odbc_drivers_for_sql_server()  # Truy vấn thông tin deiver từ máy tính
        # Tạo combobox để người dùng lựa chọn driver
        self.cbo_driver = ctk.CTkComboBox(Login_Frame, values=drivers, width=260)
        self.cbo_driver.grid(row=0, column=1, padx=8, pady=6, sticky="w")
        
        if drivers:
            # nếu có config cũ -> set theo config hoặc tự động lấy driver đầu tiên trong danh sách driver tìm được ở thiết bị
            self.cbo_driver.set(self.owner.config["connection"].get("driver") or drivers[0])

        # Server
        ctk.CTkLabel(Login_Frame, text="Server/Instance:").grid(row=1, column=0, padx=(12,8), pady=6, sticky="w")
        self.ent_server = ctk.CTkEntry(Login_Frame, width=260, placeholder_text="HOST\\INSTANCE hoặc 10.0.0.5,1433")
        self.ent_server.grid(row=1, column=1, padx=8, pady=6, sticky="w")

        # Nếu có thông tin lưu trữ đăng nhập thì tự động điền vào
        if self.owner.config["connection"].get("server"):
            self.ent_server.insert(0, self.owner.config["connection"]["server"])

        # Auth mode
        ctk.CTkLabel(Login_Frame, text="Chế độ đăng nhập:").grid(row=2, column=0, padx=(12,8), pady=6, sticky="w")
        self.auth_mode = ctk.StringVar(value=self.owner.config["connection"].get("auth_mode","sql"))

        # Tạo frame chứa 2 nút lựa chọn chế độ đăng nhập
        auth_mode_frame = ctk.CTkFrame(Login_Frame, fg_color="transparent")
        auth_mode_frame.grid(row=2, column=1, padx=8, pady=6, sticky="w")
        # Tạo radiobuton, chỉ được lựa chọn 1 trong 2 nút
        ctk.CTkRadioButton(auth_mode_frame, text="SQL Server (sa/…)", variable=self.auth_mode, value="sql", command=self._toggle_auth).pack(side="left", padx=(0,12))
        ctk.CTkRadioButton(auth_mode_frame, text="Windows", variable=self.auth_mode, value="windows", command=self._toggle_auth).pack(side="left")

        # User/Pass
        ctk.CTkLabel(Login_Frame, text="Username:").grid(row=3, column=0, padx=(12,8), pady=6, sticky="w")
        self.ent_user = ctk.CTkEntry(Login_Frame, width=260, placeholder_text="sa hoặc user SQL")
        self.ent_user.grid(row=3, column=1, padx=8, pady=6, sticky="w")
        # Nếu có thông tin đăng nhập thì lấy từ tệp json cấu hình và đưa lên
        if self.owner.config["connection"].get("username"):
            self.ent_user.insert(0, self.owner.config["connection"]["username"])

        ctk.CTkLabel(Login_Frame, text="Password:").grid(row=4, column=0, padx=(12,8), pady=6, sticky="w")
        self.ent_pass = ctk.CTkEntry(Login_Frame, width=260, placeholder_text="••••••••", show="*")
        self.ent_pass.grid(row=4, column=1, padx=8, pady=6, sticky="w")

        # Nút kểt nối tới CSDL
        self.btn_connect = ctk.CTkButton(Login_Frame, text="Kết nối", command=self._do_connect)
        self.btn_connect.grid(row=5, column=0, columnspan=2, padx=8, pady=(10,6), sticky="ew")

        # Textbox hiển thị nội dung kết nối
        self.lbl_status = ctk.CTkTextbox(Login_Frame, width=1, height=1, text_color="#f59e0b", wrap = "word")
        self.lbl_status.grid(row=6, column=0, columnspan=2, padx=8, pady=(4,12), sticky="nsew")

        # Frame chứa danh sách DB bên phải
        Database_Frame = ctk.CTkFrame(self)
        Database_Frame.grid(row=1, column=1, padx=(0,16), pady=8, sticky="nsew")
        Database_Frame.grid_rowconfigure(1, weight=1)
        Database_Frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(Database_Frame, text="Danh sách Database", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=12, pady=(12,8), sticky="w")
        # Treeview hiển thị danh sách Database
        self.tv = ttk.Treeview(Database_Frame, columns=("name","state","recovery"), show="headings")
        for col, w in ("name",220),("state",120),("recovery",120):
            self.tv.heading(col, text=col.title())
            self.tv.column(col, width=w, anchor="w")

        self.tv.grid(row=1, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(Database_Frame, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        vsb.grid(row=1, column=1, sticky="ns")

        # Frame chứa các chức năng 
        Control_DB_Frame = ctk.CTkFrame(Database_Frame, fg_color="transparent")
        Control_DB_Frame.grid(row=2, column=0, padx=12, pady=8, sticky="ew")
        Control_DB_Frame.grid_columnconfigure(0, weight=1)
        Control_DB_Frame.grid_columnconfigure(1, weight=1)
        self.btn_refresh = ctk.CTkButton(Control_DB_Frame, text="↻ Tải lại", command=self._refresh_dbs, state="disabled")
        self.btn_add     = ctk.CTkButton(Control_DB_Frame, text="➕ Thêm DB danh sách backup", command=self._add_selected, state="disabled")
        self.btn_refresh.grid(row=0, column=0, padx=(0,6), sticky="ew")
        self.btn_add.grid(row=0, column=1, padx=(6,0), sticky="ew")

        # Ẩn hiện ô nhập tài khoản đăng nhập SQL Server
        self._toggle_auth()

    # ----------------- event handlers -----------------
    def _toggle_auth(self):
        """
        Ẩn hiện ô nhập tài khoản đăng nhập tùy theo chế độ đăng nhập
        """
        mode = self.auth_mode.get()
        # Nếu sử dụng đăng nahapj bằng window thì ẩn 2 ô nhập tài khoản/ mật khẩu
        if mode == "windows":
            self.ent_user.configure(state="disabled")
            self.ent_pass.configure(state="disabled")
        else:
            self.ent_user.configure(state="normal")
            self.ent_pass.configure(state="normal")

    def insert_status(self, text, color ="#f59e0b" ):
        """
        Hiển thị nội dung vào textbox
        """
        self.lbl_status.configure(state="normal", text_color= color)
        self.lbl_status.delete("0.0", "end")
        self.lbl_status.insert("end", text= text + "\n")
        self.lbl_status.see("end")
        self.lbl_status.configure(state="disabled")

    def _do_connect(self):
        """
        Kết nối tới CSDL
        """
        # Lấy thông tin kết nối tới SQL Server
        driver = self.cbo_driver.get().strip()
        server = self.ent_server.get().strip()
        mode   = self.auth_mode.get()

        # Chỉ lấy thông tin đăng nhập nếu sử dụng chế độ đăng nhập bằng tài khoản
        user   = self.ent_user.get().strip() if mode == "sql" else None
        pwd    = self.ent_pass.get().strip() if mode == "sql" else None

        if not driver:
            messagebox.showwarning("Thiếu thông tin", "Chọn ODBC Driver từ danh sách. \
                                   \nNếu không tìm thấy danh sách driver, vui lòng cài đặt từ trang chủ Microsoft")
            return
        if not server:
            messagebox.showwarning("Thiếu thông tin", "Nhập Server/Instance.")
            return
        if mode == "sql" and (not user or not pwd):
            messagebox.showwarning("Thiếu thông tin", "Nhập Username/Password cho SQL Auth.")
            return

        # Tạo chuỗi kết nối tới SQL Server tương ứng
        conn_str = _build_conn_str(driver, server, mode, user, pwd)

        # Hiển thị quá trình kết nối và khóa ko cho bấm nút kết nối nữa
        self.insert_status(text= "Đang kết nối...")
        self.btn_connect.configure(state="disabled")

        # Lưu config kết nối (không lưu password) vào tệp cấu hình
        self.owner.config["connection"].update({
            "driver": driver,
            "server": server,
            "auth_mode": mode,
            "username": user,
        })

        # Ghi dữ liêu vào tệp json cấu hình
        self.owner.save_config(silent = True)

        # hiển thị popup
        self.loading.show()

        # Tạo luồng mới để kết nối tới SQL Server
        threading.Thread(target=self.connect_in_thread, args=(conn_str,), daemon= True).start()

    def connect_in_thread(self, connect_string):
        try:
            # Kết nối tới SQL Server
            conn = pyodbc.connect(connect_string)
            # Lưu kết nối
            self.conn = conn
            self.owner.conn = conn  # chia sẻ cho toàn trang  

            # Cập nhật thông tin lên giao diện chính
            self.after(0, self.update_after_connect_SQL_Server)

            # Ẩn popup loading và hiển thị thông báo
            self.loading.schedule_hide()
            self.after(0, lambda: messagebox.showinfo("Đã kết nối", f"Kết nối tới SQL Server thành công."))
        except Exception as e:
            # Hiện thị lỗi
            self.after(0, lambda err=e: self.update_after_connect_SQL_Server(success=False, error= str(err)))

            # Ẩn popup và ghi log
            # self.after(0, self.loading.hide)
            self.loading.schedule_hide()
            logger.error(f"Xảy ra lỗi trong quá trình kết nối tới SQL Server: {e}")            
    
    def update_after_connect_SQL_Server(self, success = True, error = ""):
        """
        Cập nhật giao diện chương trình sau khi kết nối tới CSDL
        """
        if success:
            # Hiển thị trạng thái đã kết nối
            self.insert_status("Đã kết nối", color="#22c55e")

            # Kích hoạt các nút chức năng
            self.btn_refresh.configure(state="normal")
            self.btn_add.configure(state="normal")

            # Lấy danh sách Database từ SQL Server
            self._refresh_dbs()
        else:
            # Thông báo lỗi
            self.insert_status(text=f"Không thể kết nối tới SQL Server: \n {error}")
        
        # Sau cùng mở lại nút bấm kết nối
        self.btn_connect.configure(state="normal")

    def _refresh_dbs(self):
        """
        Truy vấn danh sách Database và hiển thị lên frame bên phải
        """
        # Nếu chưa kết nối thì không làm gì cả
        if not self.conn:
            return
        
        # Khóa nút Tải lại, ko cho click liên tục
        self.btn_refresh.configure(state="disabled")

        # Xóa các hàng cũ trong Treeview
        for row in self.tv.get_children():
            self.tv.delete(row)

        # Hiện popup loading
        self.loading.show()
        # Gọi truy vấn DB trong luồng riêng
        threading.Thread(target= self.get_list_database_in_thread, daemon= True).start()

    def get_list_database_in_thread(self):
        """
        Truy vấn danh sách Databse từ SQL Server đã kết nối
        """
        try:
            # Tạo con trỏ
            cur = self.conn.cursor()
            # Thực hiện truy vấn
            cur.execute("""
                SELECT name, state_desc, recovery_model_desc
                FROM sys.databases
                WHERE database_id > 4  -- Các DB có id <= 4 là DB gốc: master, tempdb, model, msdb
                ORDER BY name ASC
            """)
            # Lấy dữ liệu trả về
            data = cur.fetchall()

            # Ẩn popup loading
            self.loading.schedule_hide()
            # Gọi hàm sửa giao diện
            self.after(0, lambda: self.insert_database_into_treeview(data= data))
            
        except Exception as e:
            # Ẩn popup và hiển thị lỗi
            self.loading.schedule_hide()
            self.after(0, lambda err=e: self.insert_status(text=f"Xảy ra lỗi khi truy vấn thông tin database: \n{str(err)}"))
            self.after(0, lambda err=e: messagebox.showerror("Lỗi kết nối", f"Không thể lấy danh sách database") )
    
    def insert_database_into_treeview(self, data):
        """
        Hiển thị danh sách Database lên treeview
        """
        # Mở lại chức năng refresh
        self.btn_refresh.configure(state="normal")
        # Điền dữ liệu vào treeview
        for name, state, rm in data:
            self.tv.insert("", "end", values=(name, state, rm))

    def _add_selected(self):
        """
        Thêm 1 database từ treeview vào danh sách Database sử dụng backup
        """
        # Lấy danh sách item mà đang được chọn từ treeview (Có thể người dùng chọn nhiều item một lúc)
        items = self.tv.selection()
        if not items:
            messagebox.showinfo("Chưa chọn", "Chọn ít nhất một DB.")
            return
        
        # Danh sách chứa các DB cần thêm
        added = []
        # Duyệt qua từng item và lưu vào danh sách
        for iid in items:
            name = self.tv.item(iid, "values")[0]
            if self.owner.add_database_for_backup(name):
                added.append(name)
        # Nếu có databse được thêm thì lưu nó vào tệp config
        if added:
            # cập nhật config và lưu
            self.owner.config["databases"] = sorted(self.owner.selected_databases)
            self.owner.save_config(silent = True)
            messagebox.showinfo("Đã thêm", "\n".join(added))
        else:
            messagebox.showinfo("Thông báo", "Các DB đã có trong danh sách.")