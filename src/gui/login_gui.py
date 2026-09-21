"""
Giao diện đăng nhập chương trình
"""
from __future__ import annotations
import queue
import threading
import time
import logging
import string
import secrets
from datetime import datetime, timedelta, timezone
import re
from tkinter import messagebox, TclError
import customtkinter as ctk
from PIL import Image

# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
# import os,sys
# PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.append(PROJECT_DIR)

from utils.constants import FILE_PATH
from utils.resource import resource_path
from utils.secure_session_store import SessionStore, StoreError, scrub_legacy_config
from services.auth_adapter import (DatabaseAuthAdapter, AuthSession, AuthError,
    InvalidSession, BackendUnavailable, REMEMBER_DAYS)
from services.database_service import MyDatabase
from services.email_service import InternalEmailSender
from auth.google_auth import GoogleAuthService



logger = logging.getLogger(__name__)


class NewAccountError(RuntimeError):
    """Thông báo đã làm sạch, có thể hiển thị cho user."""

class LoginWindow(ctk.CTkToplevel):
    """
    Giao diện đăng nhập chương trình
    """
    def __init__(self, master, on_success, on_close, software_name="Quan", *,
                 auto_login=True, session_store=None, auth_adapter=None,
                 account_service=None, oauth_factories=None):

        super().__init__(master)
        # Khởi tạo các trạng thái
        self._closed = False                                                    # Cửa sổ này đã đóng hay chưa
        self._completed = False                                                 # Đã hoàn tất quá trình đăng nhập chưa, tránh đăng nhập nhiều lần
        self._busy = False                                                      # Giao diện có đang rảnh để xử lý các thao tác mới hay không
        self._operation = 0                                                     # Đánh số các thao tác để loại các thao tác cũ
        self._thread = None                                                     # Dùng để theo dõi thread xác thực chính
        self._cancel = threading.Event()                                        # Tín hiệu hủy thread
        self._delivery_lock = threading.Lock()                                  # Khóa luồng
        self._events = queue.Queue()                                            # Tạo hàng đợi lưu trữ kết quả từ luồng
        self._timers = set()                                                    # List chứa các ID lệnh self.after(), dùng khi đóng cửa sổ sẽ hủy các lệnh này
        self._deadline = 0.0                                                    # Mốc hết thời gian của thao tác
        self._oauth_waiting = False                                             # Đang đợi kết quả từ oauth
        self._oauth_service = None                                              # Tạo service xác thực bằng tài khoản MXH
        self._auto_login_allowed = auto_login                                   # Cho phép tự đăng nhập nếu có lưu trữ thông tin đăng nhập
        self.on_success, self.on_close = on_success, on_close                   # Hàm đăng nhập thành công, thất bại
        self.software_name = software_name                                      # Tên chương trình
        self.adapter = auth_adapter or DatabaseAuthAdapter()                    # Class lưu phiên đăng nhập
        self.account_service = account_service                                  # Nơi quản lý các tài khoản
        self.oauth_factories = oauth_factories or {}                            # Cấu hình thông tin đăng nhập bằng Google hoặc Facebook
        self.store = session_store                                              # Lưu phiên đăng nhập
        self._storage_warning = None                                            # Cảnh báo nếu có vấn đề với phiên đăng nhập

        # Kiểm tra nếu chưa truyền store thì tạo store mặc định
        try:
            if self.store is None:
                # Mặc định nơi lưu trữ phiên đăng nhập là: AppData\Local\Quan\Auth\remembered-session.bin
                self.store = SessionStore()
            # Tiến hành dọn các trường quan trọng như password, token khỏi file cấu hình
            scrub_legacy_config(FILE_PATH["LOGIN_CONFIG"])
        except (OSError, StoreError):
            self._storage_warning = "Chưa xử lý được nơi lưu phiên/cấu hình cũ. Hãy kiểm tra hướng dẫn trước khi dùng ghi nhớ."

        # Khởi tạo các frame
        self.forgot_password_frame = None
        self.create_account_frame = None
        self.login_frame = None

        # Khởi tạo các nút bấm và ô nhập
        self.email_account = None
        self.otp_reset = None
        self.get_otp_button = None
        self.new_password = None
        self.new_password_again = None
        self.email_entry = None
        self.username_entry = None
        self.password_entry = None
        self.password_confirm_entry = None

        # DB
        self.database = MyDatabase()
        # Gửi thư tự động
        self.email_sender = InternalEmailSender()

        # Thiết lập thông tin chương trình
        self.title("Đăng nhập phần mềm")
        self.config(bg="white")
        self.resizable(False, False)

        # Lắng nghe sự kiện đóng cửa sổ
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Background cho giao diện đăng nhập
        with Image.open(resource_path("assets\\images\\background\\background_login_dark.jpg")) as image:
            self._bg_image = ctk.CTkImage(dark_image=image.copy(), size=(500, 500))
        ctk.CTkLabel(self, image=self._bg_image, text="").grid(row=0, column=0)

        # Tạo frame đăng nhập
        self.create_login_frame()
        # Đối với cửa sổ toplevel thì cần thêm chút độ trễ cho đến khi cửa sổ tạo thành thì mới thay được icon
        self._schedule(300, self._set_icon)
        # Kiểm tra hàng đợi sau 50ms
        self._schedule(50, self._poll)

        # Nếu có cảnh báo thì hiển thị
        if self._storage_warning:
            self._schedule(100, lambda: messagebox.showwarning("Lưu đăng nhập", self._storage_warning, parent=self))
        elif auto_login:
            # Thử tiến hành đăng nhập nếu có dữ liệu được lưu
            self._schedule(200, self.try_auto_login_from_session)

    def _set_icon(self):
        """
        Thiết lập icon cho giao diện đăng nhập
        """
        try:
            self.iconbitmap(resource_path("assets\\images\\ico\\ico.ico"))
        except (TclError, OSError):
            logger.error("Không thể thiết lập icon cho chương trình đăng nhập")

    def _schedule(self, delay, callback):
        """
        Lên lịch thực hiện 1 hàm sau 1 khoảng thời gian `delay`
        """
        # Nếu cửa sổ đã đóng thì tắt
        if self._closed:
            return

        # Khởi tạo id cho hàm này
        timer = None
        def run():
            """
            Hàm chính để chạy
            """
            # Khi bắt đầu chạy thì xóa ID khỏi bộ lập lịch đang chờ
            self._timers.discard(timer)
            # Kiểm tra lần nữa nếu chương trình chưa đóng thì mới tiến hành chạy hàm
            if not self._closed:
                callback()

        # Đặt lịch chạy và gán ID vào bộ lập lịch
        timer = self.after(delay, run)
        self._timers.add(timer)

    def create_login_frame(self):
        """
        Tạo giao diện đăng nhập
        """
        # Frame đăng nhập
        self.login_frame = ctk.CTkFrame(self, fg_color="#D9D9D9", bg_color="white", height=350, width=300, corner_radius=20)
        self.login_frame.grid(row=0, column=1, padx=40)

        # Thông báo chào mừng login
        self.welcome_label = ctk.CTkLabel(self.login_frame, text="Chào mừng quay trở lại! \nĐăng nhập để tiếp tục", text_color="black", font=("",25,"bold"))
        self.welcome_label.grid(row=0, column=0, sticky="nw", pady=30, padx=10)

        # Ô nhập tên đăng nhập
        self.email_login = ctk.CTkEntry(self.login_frame, text_color="white", placeholder_text="Email đăng nhập", fg_color="black", placeholder_text_color="white",
                                font=("",16,"bold"), width=200, corner_radius=15, height=45)
        self.email_login.grid(row=1,column=0,sticky="nwe",padx=30)

        # Ô nhập password
        self.show_password_var = ctk.BooleanVar()
        self.passwd_entry = ctk.CTkEntry(self.login_frame,text_color="white",placeholder_text="Mật khẩu",fg_color="black",placeholder_text_color="white",
                                font=("",16,"bold"), width=200,corner_radius=15, height=45, show="*")
        self.passwd_entry.grid(row=2,column=0,sticky="nwe",padx=30,pady=(20,0))

        # Gắn sự kiện Enter cho cả hai ô nhập: email và password, khi nhấn enter tự động đăng nhập
        self.email_login.bind("<Return>", lambda event: self.check_login())   # Khi nhấn Enter trên email
        self.passwd_entry.bind("<Return>", lambda event: self.check_login())  # Khi nhấn Enter trên password

        # Hiển thị password
        self.show_password = ctk.CTkCheckBox(master=self.login_frame, text="Hiện mật khẩu", font=('', 12), text_color="black", height=10,
                                             command=lambda: self.toggle_password(self.passwd_entry, self.show_password_var), variable=self.show_password_var)
        self.show_password.grid(row=3,column=0,sticky="nw", padx=(30,0))

        # Quên mật khẩu
        self.forget_password_label = ctk.CTkLabel(master=self.login_frame, text="Quên mật khẩu?", font=('', 10), text_color="black")
        self.forget_password_label.grid(row=3,column=0,sticky="ne", padx= (0,10))

        # Chuyển đổi hình dạng chuột khi di chuyển vào label và quay về hình dạng ban đầu khi di chuột rời label
        self.forget_password_label.bind("<Enter>", lambda event: self.forget_password_label.configure(cursor="hand2"))
        self.forget_password_label.bind("<Leave>", lambda event: self.forget_password_label.configure(cursor="arrow"))

        # Mở cửa sổ quên mật khẩu khi ấn vào nút quên mật khẩu
        self.forget_password_label.bind("<Button-1>", self.open_forgot_password_frame)

        # Biến boolean để lưu trạng thái checkbox
        self.remember_var = ctk.BooleanVar(value=False)
        # Checkbox ghi nhớ đăng nhập
        self.remember_check = ctk.CTkCheckBox(master=self.login_frame, text=f"Ghi nhớ đăng nhập {REMEMBER_DAYS} ngày", variable=self.remember_var, text_color= "black")
        self.remember_check.grid(row=4, column=0, columnspan=2, sticky = "nw", padx=(30, 0))

        # Mở cửa sổ tạo tài khoản mới
        create_acc_btn = ctk.CTkButton(self.login_frame, text="Tạo tài khoản!", cursor="hand2", text_color="black", font=("",15),
                                fg_color= "transparent", hover_color= "#D9D9D9", anchor= "nw", command=self.open_create_account_frame)
        create_acc_btn.grid(row=5,column=0,sticky="w",pady=20,padx=20)

        # Nút đăng nhập
        login_btn = ctk.CTkButton(self.login_frame, text="Đăng nhập", font=("",15,"bold"), height=40, width=60, fg_color="#0085FF", cursor="hand2",
                        corner_radius=15, command= self.check_login)
        login_btn.grid(row=5,column=0,sticky="ne",pady=20, padx=35)

        # Phương thức đăng nhập khác
        another_login = ctk.CTkLabel(master=self.login_frame, text="Hoặc đăng nhập bằng:", font=("",15), text_color="black", anchor= "center")
        another_login.grid(row=6,column=0, padx= (0,10))

        # Google login
        g_logo = ctk.CTkImage(Image.open(resource_path("assets\\images\\login_img\\google_logo.png")).resize((20, 20), Image.Resampling.LANCZOS))
        self.g_button = ctk.CTkButton(master=self.login_frame, width=100, image=g_logo, text="Google", corner_radius=6, fg_color="white",
                                      text_color="black", compound="left", hover_color="#f0f0f0", anchor="w", cursor="hand2", command= self.login_with_google_click)
        self.g_button.grid(row=7,column=0,sticky="w",pady=(0,20), padx=35)

        # Facebook login
        fb_logo = ctk.CTkImage(Image.open(resource_path("assets\\images\\login_img\\fb_logo.png")).resize((20, 20), Image.Resampling.LANCZOS))
        self.fb_button = ctk.CTkButton(master=self.login_frame, width=100, image=fb_logo, text="Facebook", corner_radius=6, fg_color="white",
                                       text_color="black", compound="left", hover_color="#f0f0f0", anchor="w", cursor="hand2", command= self.login_with_facebook_click)
        self.fb_button.grid(row=7,column=0,sticky="e",pady=(0,20), padx=35)

        # Một khoảng đệm để sau này hiện thông báo đang xác thực và đi kèm là thanh tiến trình hiển thị
        self.status_label = ctk.CTkLabel(self.login_frame, text="", text_color="black", wraplength=300)
        self.status_label.grid(row=8, column=0, padx=20, pady=5)
        self.progress = ctk.CTkProgressBar(self.login_frame, mode="indeterminate")
        self.progress.grid(row=9, column=0, padx=20, pady=5, sticky="ew")
        self.progress.grid_remove()

    def open_forgot_password_frame(self, _event=None):
        """
        Tạo một frame để thực hiện thay đổi mật khẩu
        """
        # _event là biến sự kiện được truyền từ bind, nhưng không sử dụng trong hàm nên đặt tên là _event để tránh cảnh báo pylint
        # Kiểm tra chương trình có đang thực hiện thao tác khác không
        if self._busy or (self._thread and self._thread.is_alive()):
            return

        # Xóa bỏ frame đăng nhập
        self._auto_login_allowed = False
        self.login_frame.destroy()

        # Tạo frame quên mật khẩu
        self.forgot_password_frame = ctk.CTkFrame(self, fg_color="#D9D9D9", bg_color="white", height=350, width=300, corner_radius=20)
        self.forgot_password_frame.grid(row=0, column=1, padx=(10,40))

        # Tiêu đề và các trường nhập mật khẩu mới
        title = ctk.CTkLabel(self.forgot_password_frame, text="Thay đổi mật khẩu", text_color="black", font=("",25,"bold"))
        title.grid(row=0, column=0, columnspan = 2, sticky="nwes", pady=20, padx=10)

        self.email_account = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Email đã đăng ký", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=260, corner_radius=15, height=45)
        self.email_account.grid(row=1, column=0, columnspan = 2, padx = 5, pady=(20, 10))

        self.otp_reset = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Nhập OTP", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=150, corner_radius=15, height=45)
        self.otp_reset.grid(row=2, column=0, padx = 5, pady=5)

        self.get_otp_button = ctk.CTkButton(self.forgot_password_frame, text="Lấy OTP", font=("", 15, "bold"), fg_color="#0085FF", cursor="hand2",
                                   corner_radius=15, width= 100, command= self.get_otp_for_reset_password)
        self.get_otp_button.grid(row=2, column=1, pady=5)

        self.new_password = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Mật khẩu mới", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=260, corner_radius=15, height=45, show = "*")
        self.new_password.grid(row=3, column=0, columnspan = 2, padx = 5, pady=5)

        self.new_password_again = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Nhập lại mật khẩu", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=260, corner_radius=15, height=45, show = "*")
        self.new_password_again.grid(row=4, column=0, columnspan = 2, padx = 5, pady=10)

        reset_btn = ctk.CTkButton(self.forgot_password_frame, text="Đặt lại mật khẩu", font=("", 15, "bold"), fg_color="#0085FF", cursor="hand2",
                                   corner_radius=15, command= self.reset_password)
        reset_btn.grid(row=5, column=0, columnspan = 2, pady=5)

        back_btn = ctk.CTkButton(self.forgot_password_frame, text="Quay về trang đăng nhập", text_color="black", font=("", 12), cursor="hand2",
                                  fg_color= "transparent", hover_color= "#D9D9D9", command=self.back_to_login_frame)
        back_btn.grid(row=6, column=0, columnspan = 2, pady=5)

    def open_create_account_frame(self):
        """
        Tạo frame để tạo một tài khoản mới
        """
        # Xóa bỏ frame đăng nhập
        if self._busy or (self._thread and self._thread.is_alive()):
            return
        self._auto_login_allowed = False
        self.login_frame.destroy()

        # Tạo frame tạo tài khoản
        self.create_account_frame = ctk.CTkFrame(self, fg_color="#D9D9D9", bg_color="white", height=350, width=300, corner_radius=20)
        self.create_account_frame.grid(row=0, column=1, padx=40)

        # Tiêu đề và các trường nhập tài khoản mới
        title = ctk.CTkLabel(self.create_account_frame, text="Tạo tài khoản mới", font=("", 20, "bold"), text_color="black")
        title.grid(row=0, column=0, pady=20, padx = 20)

        # Các mục để nhập thông tin tài khoản
        self.email_entry = ctk.CTkEntry(self.create_account_frame, text_color="white", placeholder_text="Email đăng ký", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=200, corner_radius=15, height=45)
        self.email_entry.grid(row=1, column=0, pady=(5,10), padx = 40)

        self.username_entry = ctk.CTkEntry(self.create_account_frame, text_color="white", placeholder_text="Tên người dùng", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=200, corner_radius=15, height=45)
        self.username_entry.grid(row=2, column=0, pady=(10,10), padx = 40)

        self.password_entry = ctk.CTkEntry(self.create_account_frame, text_color="white", placeholder_text="Mật khẩu", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=200, corner_radius=15, height=45, show = "*")
        self.password_entry.grid(row=3, column=0, pady=(10,10), padx = 40)

        self.password_confirm_entry = ctk.CTkEntry(self.create_account_frame, text_color="white", placeholder_text="Xác nhận mật khẩu", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=200, corner_radius=15, height=45, show = "*")
        self.password_confirm_entry.grid(row=4, column=0, pady=(10,20), padx = 40)

        # Nút bấm tạo tài khoản và quay trở về trang đăng nhập
        create_btn = ctk.CTkButton(self.create_account_frame, text="Tạo tài khoản", font=("", 15, "bold"), fg_color="#0085FF", cursor="hand2",
                                    corner_radius=15 , command= self.create_new_account)
        create_btn.grid(row=5, column=0, pady=(10,5), padx = 20)

        back_btn = ctk.CTkButton(self.create_account_frame, text="Quay về trang đăng nhập", text_color="black", font=("", 12), cursor="hand2",
                                 fg_color= "transparent", hover_color= "#D9D9D9", command=self.back_to_login_frame)
        back_btn.grid(row=6, column=0, pady=(5,10), padx = 20)

    def toggle_password(self, pwd_entry: ctk.CTkEntry, show_password_var: ctk.BooleanVar):
        """
        Hiển thị mật khẩu khi người dùng chọn chức năng hiển thị mật khẩu
        """
        if show_password_var.get():
            pwd_entry.configure(show="")
        else:
            pwd_entry.configure(show="*")

    def _current_frame(self):
        """
        Tìm form hiện tại
        """
        # Duyệt qua ba form chính là đăng nhập, quên mật khẩu, tạo mật khẩu mới
        for frame in (self.forgot_password_frame, self.create_account_frame, self.login_frame):
            # frame nào đã được tạo và widget TK vẫn còn tồn tại thì trả về frame đó, nếu không thì trả về none
            if frame is not None and frame.winfo_exists():
                return frame
        return None

    def _set_busy(self, busy):
        """
        Đánh dấu là giao diện đang bận xử lý hoặc không bận  
        Ví dụ khi đang xác thực đăng nhập thì phải set giao diện đang bận, và khóa các nút bấm lại
        """
        # Khóa/ mở form
        self._busy = busy

        # lấy form hiện tại
        frame = self._current_frame()
        if frame:
            # duyệt qua các widget con trực tiếp của frame này
            for child in frame.winfo_children():
                # Xử lý trạng thái các nút, ô nhập và checkbox
                if isinstance(child, (ctk.CTkButton, ctk.CTkEntry, ctk.CTkCheckBox)):
                    child.configure(state="disabled" if busy else "normal")

        # Nếu đang là form login
        if self.login_frame is not None and self.login_frame.winfo_exists():
            # Hiện thị trạng thái đang xác thực lên màn hình
            self.status_label.configure(text="Đang xác thực…" if busy else "")
            if busy:
                self.progress.grid()
                self.progress.start()        # Cho thanh tiến trình chạy qua lại để nhận biết
            else:
                self.progress.stop()
                self.progress.grid_remove()  # Ẩn thanh tiến trình

    def _begin(self):
        """
        Bắt đầu 1 thao tác mới
        """
        # nếu chương trình đã hoàn tất nhiệm vụ, đang bận xử lý hoặc đã đóng giao diện thì không làm gì hết
        if self._closed or self._completed or self._busy:
            return None

        # Nếu thread chưa kết thúc, có nghĩa là đang có tác vụ hoạt động, vì vậy thông báo cảnh báo không chạy nữa
        if self._thread is not None and self._thread.is_alive():
            messagebox.showinfo("Đang xử lý", "Kết nối trước chưa kết thúc. Vui lòng chờ hoặc đóng cửa sổ.", parent=self)
            return None

        # Đánh số thao tác, ví dụ lần đầu = 1, lần tiếp theo = 2, ....
        self._operation += 1
        # Tạo tín hiệu hủy cho lần chạy này và đặt thời gian chờ cho thao tác này là 45s
        self._cancel = threading.Event()
        self._deadline = time.monotonic() + 45
        # Đánh dấu là chương trình bận để bắt đầu thao tác này
        self._set_busy(True)
        return self._operation

    def _submit(self, function, *args, kind="auth", operation=None):
        """
        Chạy hàm trên worker  
        - function: hàm cần chạy.
        - *args: gom các đối số vị trí thành tuple.
        - kind: loại kết quả, mặc định là xác thực.
        - operation: ID thao tác có sẵn, dùng khi tiếp tục OAuth.
        """
        # Nếu chưa có ID thì tiến hành tạo ID thao tác
        if operation is None:
            operation = self._begin()

        # Nếu không thể tạo được ID thì không thực hiện hàm
        if operation is None or self._closed:
            return

        # Lấy tham chiếu cho tín hiệu hủy thread, vì nếu có lỡ bị thay thế biến khác thì event stop cũ (self._cancel) đã được lưu ở cancel rồi
        cancel = self._cancel
        def worker():
            """
            Hàm chạy chính
            """
            try:
                # Chạy hàm với các tham số arg (*arg sẽ bung tuple ra các tham số)
                result = function(*args)
                # Đóng gói kết quả thành một tuple
                event = (operation, kind, result)

            except AuthError as error:
                event = (operation, "error", error)

            except Exception as e:     # pylint: disable=broad-except
                # Không đưa lỗi DB/connection string/token vào log hoặc UI.
                event = (operation, "error", BackendUnavailable(f"Không thể hoàn tất thao tác. Lỗi: {str(e)}"))

            # Giữ khóa trong đoạn kiểm tra
            with self._delivery_lock:
                # Nếu thao tác bị hủy hoặc cửa sổ đóng thì không gửi kết quả đến queue _event
                discard = cancel.is_set() or self._closed
                if not discard:
                    self._events.put(event)

            # Nếu kết quả bị hủy (discard == true) và đã tạo token mới thì tiến hành thu hồi token mới
            if discard and isinstance(event[2], AuthSession) and event[2].newly_issued:
                self.adapter.revoke(event[2].token)

        # Bắt đầu chạy nhiệm vụ trong thread
        self._thread = threading.Thread(target=worker, daemon=True, name="Authentication")
        self._thread.start()

    def _poll(self):
        """
        Xử lý giao diện khi hàng đợi có sự kiện cần xử lý
        """
        # Nếu thao tác vượt qua mốc chờ thì tiến hành hủy lệnh này
        if self._busy and time.monotonic() >= self._deadline:
            self._cancel.set()                              # Đánh dấu hủy và không nhận kết quả nữa
            self._operation += 1                            # Tăng ID lên 1 để đánh dấu id trước đó là cũ rồi
            self._set_busy(False)                           # Mở Form
            self._oauth_waiting = False                     # Đánh dấu không đợi xác thực nữa
            messagebox.showwarning("Hết thời gian chờ",
                "Dịch vụ phản hồi quá chậm. Bạn có thể đóng cửa sổ. "
                "Nếu là thao tác đổi dữ liệu, hãy kiểm tra kết quả trước khi thử lại.", parent=self)

        # Duyệt tối đa 30 sự kiện
        for _ in range(30):
            try:
                # Lấy kết quả từ event Queue
                operation, kind, result = self._events.get_nowait()

            except queue.Empty:
                break

            # Nếu operation này đã cũ thì xóa nó
            if operation != self._operation or self._closed:
                # Nếu là token thì cố gắng thu hồi nó
                if isinstance(result, AuthSession) and result.newly_issued:
                    self._revoke_later(result.token)

                continue

            # Xử lý oauth khi người dùng đăng nhập bằng Google/Facebook
            if kind == "oauth_info":
                # Nếu vẫn đang chờ kết quả xác thực thì tiến hành lấy thông tin
                if self._oauth_waiting:
                    self._oauth_waiting = False
                    provider, remember, info = result
                    # Xác thực đăng nhập
                    self._submit(self.adapter.oauth_login, provider, info, remember, operation=operation)

                continue

            # Mở lại form
            self._set_busy(False)

            # Xử lý đăng nhập
            if kind == "auth":
                self._complete_login(result)

            # Xử lý lỗi
            elif kind == "error":
                if isinstance(result, InvalidSession) and self.store:
                    try:
                        logger.error("Không thể đăng nhập thành công, tiến hành xóa phiên đăng nhập")
                        # Xóa file chứa thông tin
                        self.store.clear()
                    except StoreError:
                        logger.error("Không thể xóa phiên đăng nhập")

                # Mất mạng giữ phiên để lần sau thử lại; invalid session thì xóa.
                messagebox.showwarning("Đăng nhập", str(result), parent=self)
                logger.error("Đăng nhập thất bại. Lỗi: %s", str(result))

            # Xử lý thông báo
            elif kind == "message":
                messagebox.showinfo("Thông báo", str(result), parent=self)

            if self._closed:
                return

        # Lên lịch kiểm tra hàng đợi Queue cho lần tiếp theo sau 50ms
        self._schedule(50, self._poll)

    def check_login(self):
        """
        Tiến hành đăng nhập khi người dùng sử dụng tài khoản nội bộ
        """
        if self._busy or self._closed:
            return

        # Lấy dữ liệu đăng nhập từ ô nhập của người dùng
        email = self.email_login.get().strip()
        password = self.passwd_entry.get()
        remember = bool(self.remember_var.get())

        # Xác thực thông tin
        if not self.is_valid_email(email) or not password:
            messagebox.showwarning("Đăng nhập", "Hãy nhập email hợp lệ và mật khẩu.", parent=self)
            return

        if len(password) > 1024:
            messagebox.showwarning("Đăng nhập", "Mật khẩu vượt giới hạn độ dài của ứng dụng.", parent=self)
            return

        if remember and (self.store is None or self._storage_warning):
            messagebox.showwarning("Lưu đăng nhập", "Chưa thể lưu phiên an toàn. Bỏ chọn ghi nhớ để đăng nhập lần này.", parent=self)
            return

        # Bỏ tự động đăng nhập để không chạy tiếp
        self._auto_login_allowed = False
        # Tạo sự kiện kiểm tra thông tin đăng nhập
        self._submit(self.adapter.password_login, email, password, remember)

    def try_auto_login_from_session(self):
        """
        Thử đăng nhập bằng session được lưu trữ trên máy người dùng  
        Giải mã session có dạng:  
        ```
        record = {
            "version": 1,
            "email": "quan@example.com",
            "provider": "local",
            "session_token": "<token đã lưu>",
            "expires_at": "2026-10-09T08:00:00+00:00",
        }
        ```
        """
        # Không chạy nếu giao diện bị tắt, đang bận, đã đóng hoặc không có store.
        if not self._auto_login_allowed or self._busy or self._closed or self.store is None:
            return

        # Đánh dấu là lần này đã thử, không được phép tự lặp lại trong cửa sổ này
        self._auto_login_allowed = False

        # Tiến hành Đọc và giải mã file DPAPI trong máy tính người dùng
        try:
            record = self.store.load()
        except StoreError:
            logger.error("Không thể đọc được file chứa phiên đăng nhập")
            messagebox.showwarning("Phiên đã lưu", "Không đọc được phiên đã lưu. Hãy đăng nhập lại.", parent=self)
            return

        # Nếu chưa có file lưu thông tin đăng nhập thì trả về để người dùng đăng nhập bằng tài khoản nội bộ
        if record is None:
            return

        # Thay thế email hiện tại bằng email đọc được từ session
        self.email_login.delete(0, "end")
        self.email_login.insert(0, record["email"])
        self.remember_var.set(True)

        # Gửi token đi kiểm tra
        self._submit(self.adapter.restore, record)

    def _revoke_later(self, token):
        """
        thu hồi token mà không chặn UI
        """
        if token:
            threading.Thread(target=self.adapter.revoke, args=(token,), daemon=True,
                             name="RevokeUnusedSession").start()

    def _complete_login(self, session):
        """
        Lưu phiên đăng nhập và mở ứng dụng. Ví dụ  
        ```
        | Phiên cũ     | Đăng nhập mới   | Xử lý                |
        | ------------ | --------------- | -------------------- |
        | A có ghi nhớ | B có ghi nhớ    | Ghi token B thay A   |
        | A có ghi nhớ | B không ghi nhớ | Xóa token A          |
        | Không có     | B không ghi nhớ | Không giữ file phiên |
        ```
        """
        # Nếu đã thành công thì bỏ qua
        if self._closed or self._completed:
            return

        # Chỉ nhận phiên đúng cấu trúc mà đã tạo ra, nếu người dùng tạo giả cấu trúc khác thì loại
        if not isinstance(session, AuthSession):
            messagebox.showerror("Đăng nhập", "Kết quả xác thực không hợp lệ.", parent=self)
            return

        # Biến này lưu giữ phiên bản cũ
        previous = None
        # Nếu có phiên đăng nhập được lưu thì đọc nó để thu hồi
        if self.store:
            try:
                previous = self.store.load()
            except StoreError:
                pass

        # Giữ cảnh báo từ adapter, ví dụ xác thực thành công nhưng không tạo được token ghi nhớ.
        warning = session.warning
        try:
            # Có token và nơi lưu sẵn sàng thì mã hóa/lưu phiên.
            if session.token and self.store is not None and not self._storage_warning:
                self.store.save(session.record())
            elif self.store is not None:
                self.store.clear()  # Không có token ghi nhớ thì xóa file cũ.

        except StoreError:
            logger.error("Có lỗi xảy ra khi cố gắng lưu hoặc xóa token khi đăng nhập")
            # Có lỗi xảy ra thì cố xóa phiên cũ để gây nhầm tài khoản
            try:
                self.store.clear()
            except StoreError:
                # Nếu vẫn không xóa được, cố thu hồi token mới.
                if session.newly_issued:
                    self._revoke_later(session.token)
                messagebox.showerror("Lưu đăng nhập",
                    "Không thể lưu hoặc xóa phiên cũ. Hãy kiểm tra quyền thư mục trước khi đăng nhập.", parent=self)

                # Không mở ứng dụng trong trạng thái lưu trữ không rõ ràng. Return luôn
                return

            # Cho đăng nhập lần này và báo không ghi nhớ được.
            warning = "Đăng nhập thành công nhưng không thể ghi nhớ trên đăng nhập trên thiết bị này."

        # Nếu có token cũ khác token mới, yêu cầu thu hồi.
        if previous and previous["session_token"] != session.token:
            self._revoke_later(previous["session_token"])

        # Đánh dấu đã hoàn tất
        self._completed = True
        # Xóa thông tin password trên ô nhập
        if self.passwd_entry is not None and self.passwd_entry.winfo_exists():
            self.passwd_entry.configure(state="normal")
            self.passwd_entry.delete(0, "end")

        if warning:
            messagebox.showwarning("Ghi nhớ đăng nhập", warning, parent=self)

        # Main nhận cả email/token/quyền; không suy đoán tài khoản từ JSON.
        self.on_success(session)

        # Dọn và hủy cửa sổ đăng nhập
        self.destroy()

    def _start_oauth(self, provider):
        """
        Bắt đầu đăng nhập bằng Google hoặc Facebook
        """
        # Lấy thông tin người dùng có chọn ghi nhớ đăng nhập hay không
        remember = bool(self.remember_var.get())
        # Không cho ghi nhớ phiên đăng nhập khi store chưa sẵn sàng
        if remember and (self.store is None or self._storage_warning):
            messagebox.showwarning("Lưu đăng nhập", "Bỏ chọn ghi nhớ đăng nhập khi nơi lưu phiên chưa sẵn sàng.", parent=self)
            return

        # Bắt đầu thao tác, lấy ID
        operation = self._begin()
        if operation is None:
            return

        # Tắt autologin và chuyển sang chờ kết quả từ Oauth
        self._auto_login_allowed = False
        self._oauth_waiting = True
        # Thời gian chờ cho việc đăng nhập là tối đa 40s
        self._deadline = time.monotonic() + 40
        try:
            # Lấy hàm service nếu được truyền vào
            factory = self.oauth_factories.get(provider)
            # Nếu được truyền vào thì dùng nó
            if factory is not None:
                service = factory()

            # Nếu sử dụng google thì chạy
            elif provider == "google":

                service = GoogleAuthService(
                    client_secret_file=resource_path("assets\\config\\google_client_secret.json"),
                    scopes=[
                        "openid",
                        "https://www.googleapis.com/auth/userinfo.email",
                        "https://www.googleapis.com/auth/userinfo.profile"
                    ])
            else:
                # Không nhúng FACEBOOK_APP_SECRET thật vào exe.
                raise AuthError("Đăng nhập Facebook hiện tại chưa thể cấu hình đăng nhập")

            # Giữ service và Event để có thể xử lý kết quả hoặc hủy
            self._oauth_service = service
            cancel = self._cancel

            def success(info):
                """
                Khi chạy thành công thì đưa kết quả vào hàng đợi để xử lý
                """
                with self._delivery_lock:
                    if not cancel.is_set() and not self._closed:
                        self._events.put((operation, "oauth_info", (provider, remember, info)))

            def failure(_error):
                """
                Nếu lỗi thì đưa thông tin lỗi vào hàng đợi để hiển thị thông báo
                """
                with self._delivery_lock:
                    if not cancel.is_set() and not self._closed:
                        self._events.put((operation, "error", AuthError("Không thể đăng nhập qua nhà cung cấp. Hãy thử lại.")))

            # Bắt đầu Oauth với timeout là 30s
            service.start_login(on_success=success, on_error=failure, timeout_seconds=30)

        except Exception as error:     # pylint: disable=broad-except
            # Nếu lỗi thì thoát trạng thái chờ và mở form để người dùng thao tác mới
            self._oauth_waiting = False
            self._set_busy(False)
            messagebox.showwarning("Đăng nhập", str(error) if isinstance(error, AuthError)
                                   else "Không thể khởi tạo đăng nhập OAuth.", parent=self)

    def login_with_google_click(self):
        """
        Đăng nhập bằng dịch vụ Google
        """
        self._start_oauth("google")

    def login_with_facebook_click(self):
        """
        Đăng nhập bằng dịch vụ Facebook
        """
        self._start_oauth("facebook")

    @staticmethod
    def is_valid_email(email):
        """
        Kiểm tra email hợp lệ hay không 1 cách đơn giản
        """
        # Kiểm tra UX cơ bản, không thay xác minh email ở server.
        return len(email) <= 254 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email) is not None

    def back_to_login_frame(self):
        """
        Quay trở lại frame đăng nhập
        """
        # Nếu giao diện đang bận xử lý thao tác khác thì không cho phép quay lại giao diện đăng nhập
        if self._busy or (self._thread and self._thread.is_alive()):
            return

        # Duyệt danh sách frame và hủy nó
        for name in ("forgot_password_frame", "create_account_frame"):
            frame = getattr(self, name, None)
            if frame is not None and frame.winfo_exists():
                frame.destroy()

            setattr(self, name, None)

        # tạo lại frame đăng nhập
        self.create_login_frame()

    def generate_random_otp(self):
        """
        Tạo OTP (One Time Password) ngẫu nhiên bằng thư viện secrets và string
        """
        # Các ký tự được thêm cuối cùng
        symbols = ['*', '%', '£', '#', '$']

        password = ""
        # Tạo 8 ký tự cho mật khẩu
        for _ in range(9):
            # Mật khẩu chứa các ký tự chữ cái (thường và hoa) cùng với các chữ số
            # Nếu chỉ muốn các chữ cái thường thì sử dụng: ascii_lowercase, chữ cái hoa thì sử dụng: ascii_uppercase
            password += secrets.choice(string.ascii_letters + string.digits)

        # Thêm 1 ký tự đặc biệt vào sau cùng
        password += secrets.choice(symbols)

        return password

    def get_otp_for_reset_password(self):
        """
        Lấy mã OTP cho việc đặt lại mật khẩu
        """
        email = self.email_account.get()
        # Kiểm tra địa chỉ email có hợp lệ hay không
        if not self.is_valid_email(email):
            messagebox.showwarning("Cảnh báo","Địa chỉ email không hợp lệ.")
            return

        # Tạo ngẫu nhiên 1 OTP và cập nhật lên CSDL
        gen_otp = self.generate_random_otp()

        # Tạo thời gian hết hạn của OTP sau 10 phút
        current_time = datetime.now(timezone.utc)
        expired_otp_time = current_time + timedelta(minutes=10)

        # Backend tự sinh, gửi, hash, giới hạn thử và kiểm tra OTP; exe không đọc OTP DB.
        self._submit(self.get_otp_for_reset_password_in_thread, gen_otp, expired_otp_time, email, kind="message")

    def get_otp_for_reset_password_in_thread(self, otp, expired_otp_time, email):
        """
        Lưu mã OTP vào CSDL và gửi nó đến email người dùng trong 1 luồng riêng
        """
        # Kiểm tra email đã tồn tại hay chưa
        check_mail_result = self.database.get_username(email= email)

        # Nếu truy vấn thành công
        if check_mail_result["success"]:
            # Kiểm tra xem có tồn tại kết quả trả về không
            if not check_mail_result["data"]:
                raise NewAccountError(f"Tài khoản {email} chưa được đăng ký trên CSDL.")
        else:
            raise NewAccountError(f"Xảy ra lỗi: {check_mail_result["message"]}. \nVui lòng liên hệ bộ phận IT")

        # Cập nhật mã OTP lên CSDL
        update_otp_result = self.database.update_otp_and_time_expired(otp= otp, time_expired= expired_otp_time, email= email)
        if update_otp_result["success"]:
            # Gửi email có chứa mã OTP
            self.email_sender.send_email_for_password_reset(to_email= email, name= check_mail_result["data"][0][0], website_name= self.software_name,
                                                                OTP= otp)
        else:
            raise NewAccountError(f"{update_otp_result["message"]}. \nHãy thử lại sau.")

        # Ẩn nút getOTP và mở lại sau 30s
        self.after(0, lambda: self.get_otp_button.configure(state = "disabled"))
        self.after(1000*30, lambda: self.get_otp_button.configure(state = "normal"))

        return f"Mã OTP đã được gửi đến email {email}. Hãy kiểm tra hộp thư đến hoặc thư mục spam."

    def reset_password(self):
        """
        Đặt lại mật khẩu
        """
        # Lấy thông tin từ ô nhập
        email = self.email_account.get().strip()
        otp = self.otp_reset.get().strip()
        password = self.new_password.get()
        confirm = self.new_password_again.get()
        if not self.is_valid_email(email) or not otp or not password or password != confirm:
            messagebox.showwarning("Đặt lại mật khẩu", "Kiểm tra email, OTP và hai mật khẩu phải trùng nhau.", parent=self)
            return
        self._submit(self.update_password_for_user_in_thread, email, otp, password, kind="message")

    def update_password_for_user_in_thread(self, email, otp_code, password):
        """
        Kiểm tra thông tin mật khẩu, OTP và cập nhật mật khẩu trong 1 luồng riêng
        """
        # Kiểm tra email đã tồn tại trong CSDL chưa, đã tồn tại thì mới tiến hành cập nhật mật khẩu
        check_user = self.database.get_username(email= email)

        if check_user["success"]:
            # Lấy mã OTP và thời gian hết hạn của nó
            get_otp = self.database.verify_and_consume_otp(email= email, otp= otp_code)

            # Kiểm tra kết quả trả về
            if get_otp["success"]:
                # Nếu OTP đúng và chưa hết hạn, tiến hành thay đổi mật khẩu
                confirm_change_pw = self.database.update_password_user(email=email, password=password, user_id= get_otp["user_id"], expected_auth_version= get_otp["auth_version"])

                # Thông báo thành công
                if confirm_change_pw["success"]:
                    return "Mật khẩu của bạn đã được cập nhật thành công!"
                else:
                    raise NewAccountError(f"{confirm_change_pw["message"]}, vui lòng thử lại.")

            else:
                raise NewAccountError(f"{get_otp["message"]}. Không thể cập nhật mật khẩu \nLiên hệ bộ phận IT để xử lý.")
        else:
            raise NewAccountError(f"{check_user["message"]} \nVui lòng thử lại sau.")

    def create_new_account(self):
        """
        Đăng ký tài khoản mới
        """
        email = self.email_entry.get().strip()
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        if not self.is_valid_email(email) or not username or not password or password != self.password_confirm_entry.get():
            messagebox.showwarning("Đăng ký", "Kiểm tra lại thông tin và mật khẩu xác nhận.", parent=self)
            return
        self._submit(self.create_new_account_login_in_thread, email, username, password, kind="message")

    def create_new_account_login_in_thread(self, email, username, password):
        """
        Lưu thông tin tài khoản mới vào tệp cấu hình trong một luồng riêng
        """
        # Thêm thông tin người dùng mới vào CSDL
        # Kiểm tra email đã tồn tại trong CSDL chưa
        check_user = self.database.get_username(email= email)
        # Kiểm tra kết quả trả về
        if check_user["success"]:
            if check_user["data"]:
                raise NewAccountError(f"Email {email} đã được đăng ký. \nVui lòng sử dụng email khác.")
            else:
                raise NewAccountError(f"Có lỗi xảy ra: {check_user['message']} \nVui lòng thử lại sau.")

        # Lưu thông tin tài khoản mới vào CSDL
        create_new_user_result = self.database.create_new_user(username= username, email= email, password= password)
        if create_new_user_result["success"]:
            message=  f"Bạn đã tạo tài khoản thành công với email: {email}. \nHãy đăng nhập để sử dụng phần mềm."
            return message

        else:
            # Nếu có lỗi xảy ra trong quá trình tạo tài khoản, thông báo lỗi
            raise NewAccountError(f"{create_new_user_result['message']} \nVui lòng thử lại sau.")

    def on_closing(self):
        """
        Xử lý thao tác đóng chương trình
        """
        if not self._closed:
            self.destroy()
            self.on_close()

    def destroy(self):
        """
        Dọn dẹp tài nguyên khi đóng phần mềm
        """
        if self._closed:
            return

        # Đánh dấu đóng và báo hủy dưới cùng khóa worker
        with self._delivery_lock:
            self._closed = True
            self._cancel.set()

        # Tăng ID lên 1 để làm mọi thao tác trước nó đều là cũ
        self._operation += 1
        # Duyệt danh sách các nhiệm vụ chưa xong
        for timer in tuple(self._timers):
            try:
                # Hủy lập lịch
                self.after_cancel(timer)
            except TclError:
                pass

        # Xóa danh sách ID
        self._timers.clear()
        # Duyệt hàng đợi cho đến khi hết kết quả
        while True:
            try:
                _, _, result = self._events.get_nowait()
            except queue.Empty:
                break
            # Token mới chưa dùng thì tiến hành thu hồi
            if isinstance(result, AuthSession) and result.newly_issued:
                self._revoke_later(result.token)

        # Nếu service hỗ trợ cancel(), gọi trên worker; không join chặn UI.
        cancel = getattr(self._oauth_service, "cancel", None)
        if callable(cancel):
            threading.Thread(target=cancel, daemon=True).start()
        if hasattr(self, "progress"):
            try:
                self.progress.stop()
            except TclError:
                pass
        super().destroy()

if __name__ == "__main__":

    root = ctk.CTk()
    root.title("Test chức năng")
    # Tạo cửa sổ đăng nhập
    login_window = LoginWindow(master = root, on_success=lambda session: print(f"Đăng nhập thành công với email: {session.email}"), on_close=lambda: print("Đóng cửa sổ đăng nhập"))
    root.mainloop()
