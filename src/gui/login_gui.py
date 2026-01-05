import customtkinter as ctk
from PIL import Image
import threading
import queue
import re
import string
import secrets
from tkinter import messagebox
from datetime import datetime, timedelta
import json
import base64
import logging

# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
import os,sys
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)

# Các thư viện tự tạo import từ đây
from services.email_service import InternalEmailSender
from services.database_service import My_Database
from utils.resource import resource_path
from services.hash import Hash
from utils.loading_gif import LoadingGifLabel
from utils.constants import FILE_PATH
from auth.google_auth import GoogleAuthService
from auth.facebook_auth import FacebookAuthService

logger = logging.getLogger(__name__)

# Đường dẫn đến tệp chứa thông tin đăng nhập
CONFIG_FILE = FILE_PATH["LOGIN_CONFIG"]

# ==== CẤU HÌNH GOOGLE OAUTH ====
# File JSON tải từ Google Cloud Console (đặt trong assets/config)
GOOGLE_CLIENT_SECRET_FILE = resource_path("assets\\config\\google_client_secret.json")

# Các scope tối thiểu: lấy email + profile + openid
GOOGLE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

# ==== CẤU HÌNH FACEBOOK OAUTH ====
FACEBOOK_APP_ID = "YOUR_FACEBOOK_APP_ID"          # thay bằng App ID thật
FACEBOOK_APP_SECRET = "YOUR_FACEBOOK_APP_SECRET"  # thay bằng App Secret thật

# Port local để nhận callback, cần trùng với Redirect URI khai báo trong Facebook App
FACEBOOK_REDIRECT_PORT = 5000

# Path cho callback
FACEBOOK_REDIRECT_PATH = "/facebook_callback"

# Redirect URI đầy đủ (phải trùng với cấu hình trên Facebook App)
FACEBOOK_REDIRECT_URI = f"http://localhost:{FACEBOOK_REDIRECT_PORT}{FACEBOOK_REDIRECT_PATH}"

# Scope cần thiết (email + profile)
FACEBOOK_SCOPES = ["email", "public_profile"]

class LoginWindow(ctk.CTkToplevel):

    """
    Cửa sổ đăng nhập vào chương trình
    Chọn CSDL đã từng đăng nhập hoặc đăng nhập mới với các thông tin cần thiết
    """
    def __init__(self, master, on_success, on_close, software_name = "DucQuanApplication"):

        super().__init__(master)
        # Thử cmt để biết tác dụng của nó
        self.config(bg="white")

        self.title("Đăng Nhập phần mềm")
        # Đối với cửa sổ toplevel thì cần thêm chút độ trễ cho đến khi cửa sổ tạo thành thì mới thay được icon
        self.after(300, lambda: self.iconbitmap(resource_path("assets\\images\\ico\\ico.ico")))
        # Đảm bảo rằng cửa sổ Toplevel đứng đầu và không thể thao tác các cửa sổ khác
        # self.grab_set()
        self.resizable(False, False)

        self.on_success = on_success
        self.on_close = on_close
        self.software_name = software_name
        
        # Gửi thư tự động
        self.email_sender = InternalEmailSender()

        # Đăng nhập bằng Google
        self.google_service = GoogleAuthService(
            client_secret_file=GOOGLE_CLIENT_SECRET_FILE,
            scopes=GOOGLE_SCOPES
        )

        # Đăng nhập bằng Facebook
        self.facebook_service = FacebookAuthService(
            app_id=FACEBOOK_APP_ID,
            app_secret=FACEBOOK_APP_SECRET,
            redirect_uri=FACEBOOK_REDIRECT_URI,
            scopes=FACEBOOK_SCOPES,
            redirect_port=FACEBOOK_REDIRECT_PORT,
            redirect_path=FACEBOOK_REDIRECT_PATH
        )
        # CSDL
        self.database = My_Database()
        # Khởi tạo hàng đợi (queue) để nhận kết quả từ luồng
        self.result_queue = queue.Queue()

        # Lắng nghe sự kiện đóng cửa sổ
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Ảnh nền giao diện cửa sổ đăng nhập
        bg_img = ctk.CTkImage(dark_image=Image.open(resource_path("assets\\images\\background\\background_login_dark.jpg")), size=(500, 500))
        bg_lab = ctk.CTkLabel(self, image=bg_img, text="")
        bg_lab.grid(row=0, column=0)

        self.create_login_frame()

        # Lấy thông tin tài khoản đã lưu
        self.account = self.load_account_login()
        if self.account:
            encrypted_email = self.account[0]["email"]
            # Giải mã email
            email = base64.b64decode(encrypted_email.encode('utf-8')).decode('utf-8')

            self.email_login.insert(0, email)
        else:
            self.account = None
        
        # Tự động đăng nhập nếu trong DB có thông tin lưu trữ đăng nhập
        self.after(200, self.try_auto_login_from_session)

    def create_login_frame(self):
        """
        Tạo giao diện đăng nhập
        """

        # Frame đăng nhập
        self.login_frame = ctk.CTkFrame(self, fg_color="#D9D9D9", bg_color="white", height=350, width=300, corner_radius=20)
        self.login_frame.grid(row=0, column=1, padx=40)

        # Thông báo chào mừng login
        self.title = ctk.CTkLabel(self.login_frame, text="Chào mừng quay trở lại! \nĐăng nhập để tiếp tục", text_color="black", font=("",25,"bold"))
        self.title.grid(row=0, column=0, sticky="nw", pady=30, padx=10)

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
        self.email_login.bind("<Return>", lambda event: self.check_login())  # Khi nhấn Enter trên email
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
        self.forget_password_label.bind("<Button-1>", lambda event: self.open_forgot_password_frame())

        # Biến boolean để lưu trạng thái checkbox
        self.remember_var = ctk.BooleanVar(value=False)
        # Checkbox ghi nhớ đăng nhập
        self.remember_check = ctk.CTkCheckBox(
            master=self.login_frame,
            text="Ghi nhớ đăng nhập 30 ngày",
            variable=self.remember_var,
            text_color= "black"
        )
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

        #Google login
        g_logo = ctk.CTkImage(Image.open(resource_path("assets\\images\\login_img\\google_logo.png")).resize((20, 20), Image.LANCZOS))
        self.g_button = ctk.CTkButton(master=self.login_frame, width=100, image=g_logo, text="Google", corner_radius=6, fg_color="white", 
                                      text_color="black", compound="left", hover_color="#f0f0f0", anchor="w", cursor="hand2", command= self.login_with_google_click)
        self.g_button.grid(row=7,column=0,sticky="w",pady=(0,20), padx=35)

        #Facebook login
        fb_logo = ctk.CTkImage(Image.open(resource_path("assets\\images\\login_img\\fb_logo.png")).resize((20, 20), Image.LANCZOS))
        self.fb_button = ctk.CTkButton(master=self.login_frame, width=100, image=fb_logo, text="Facebook", corner_radius=6, fg_color="white", 
                                       text_color="black", compound="left", hover_color="#f0f0f0", anchor="w", cursor="hand2", command= self.login_with_facebook_click)
        self.fb_button.grid(row=7,column=0,sticky="e",pady=(0,20), padx=35)

    def open_forgot_password_frame(self, event=None):
        """
        Tạo một frame để thực hiện thay đổi mật khẩu
        """
        # Xóa bỏ frame đăng nhập
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

        self.OTP_reset = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Nhập OTP", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=150, corner_radius=15, height=45)
        self.OTP_reset.grid(row=2, column=0, padx = 5, pady=5)

        self.get_OTP_button = ctk.CTkButton(self.forgot_password_frame, text="Lấy OTP", font=("", 15, "bold"), fg_color="#0085FF", cursor="hand2",
                                   corner_radius=15, width= 100, command= self.get_OTP_for_reset_password)
        self.get_OTP_button.grid(row=2, column=1, pady=5)

        self.new_password = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Mật khẩu mới", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=260, corner_radius=15, height=45, show = "*")
        self.new_password.grid(row=3, column=0, columnspan = 2, padx = 5, pady=5)

        self.new_password_again = ctk.CTkEntry(self.forgot_password_frame, text_color="white", placeholder_text="Nhập lại mật khẩu", fg_color="black", placeholder_text_color="white",
                                      font=("", 16, "bold"), width=260, corner_radius=15, height=45, show = "*")
        self.new_password_again.grid(row=4, column=0, columnspan = 2, padx = 5, pady=10)

        reset_btn = ctk.CTkButton(self.forgot_password_frame, text="Đặt lại mật khẩu", font=("", 15, "bold"), fg_color="#0085FF", cursor="hand2",
                                   corner_radius=15, command= self.reset_passwword)
        reset_btn.grid(row=5, column=0, columnspan = 2, pady=5)

        back_btn = ctk.CTkButton(self.forgot_password_frame, text="Quay về trang đăng nhập", text_color="black", font=("", 12), cursor="hand2",
                                  fg_color= "transparent", hover_color= "#D9D9D9", command=self.back_to_login_frame)
        back_btn.grid(row=6, column=0, columnspan = 2, pady=5)
    
    # Định nghĩa hàm callback để xử lý kết quả sau khi gửi email
    def email_callback(self, to_email, success):
        """
        Nhận kết quả từ email và hiển thị thông báo gửi mail thành công hoặc thất bại
        """
        if success is None:
            logger.error("Lỗi khi gửi mail tới địa chỉ: %s", to_email)
            messagebox.showerror("Lỗi", "Xảy ra lỗi trong quá trình gửi mail. \n Liên hệ nhà phát triển để xử lý.")
        elif success:
            logger.info("Gửi mail thành công tới địa chỉ: %s", to_email)
            messagebox.showinfo("Thông báo", f"Đã gửi mail tới {to_email}. Hãy kiểm tra địa chỉ email của bạn.")
        else:
            logger.warning("Lỗi khi gửi mail tới địa chỉ không hợp lệ: %s", to_email)
            messagebox.showwarning("Cảnh báo", f"Không thể gửi mail tới {to_email}. \nVui lòng thử lại sau.")

    def get_OTP_for_reset_password(self):
        """
        Nút bấm gửi mã OTP đến email người dùng
        """
        logger.debug("Sử dụng chức năng lấy mã OTP")
        # Lấy email từ ô nhập
        email = self.email_account.get()
        # Kiểm tra địa chỉ email có hợp lệ hay không
        if not self.is_valid_email(email):
            messagebox.showwarning("Cảnh báo","Địa chỉ email không hợp lệ.")
            return
        
        # Tạo ngẫu nhiên 1 OTP và cập nhật lên CSDL
        gen_OTP = self.generate_random_OTP()

        # Tạo thời gian hết hạn của OTP sau 10 phút
        current_time = datetime.now()
        expired_OTP_time = current_time + timedelta(minutes=10)

        # Tạo luồng mới để cập nhật thông tin OTP về CSDL
        self.show_loading_popup()
        threading.Thread(target=self.get_OTP_for_reset_password_in_thread, args=(gen_OTP, expired_OTP_time, email ), daemon= True).start()

    def get_OTP_for_reset_password_in_thread(self, OTP, expired_OTP_time, email):
        """
        Lưu mã OTP vào CSDL và gửi nó đến email người dùng trong 1 luồng riêng
        """
        try:
            # Kiểm tra email đã tồn tại hay chưa
            check_mail_result = self.database.get_username(email= email)

            # Nếu truy vấn thành công
            if check_mail_result["success"]:
                # Kiểm tra xem có tồn tại kết quả trả về không
                if not check_mail_result["data"]:
                    self.after(0, self.hide_loading_popup)
                    self.after(0, lambda: messagebox.showinfo("Thông báo", f"Tài khoản {email} chưa được đăng ký trên CSDL.", parent= self))
                    return
                
            else:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showerror("Lỗi kết nối", f"Xảy ra lỗi: {check_mail_result["message"]}. \nVui lòng liên hệ bộ phận IT"))
                return

            # Cập nhật mã OTP lên CSDL
            update_otp_result = self.database.update_OTP_and_time_expired(OTP= OTP, time_expired= expired_OTP_time, email= email)
            if update_otp_result["success"]:
                # Gửi email có chứa mã OTP
                self.email_sender.send_email_for_password_reset(to_email= email, name= check_mail_result["data"][0][0], website_name= self.software_name,
                                                                 OTP= OTP, callback= self.callback_send_otp_to_user)
                self.after(0, self.hide_loading_popup)

            else:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showwarning("Lỗi cập nhật OTP", f"{update_otp_result["message"]}. \nHãy thử lại sau."))

            # Ẩn nút getOTP và mở lại sau 30s
            self.after(0, lambda: self.get_OTP_button.configure(state = "disabled"))
            self.after(1000*30, lambda: self.get_OTP_button.configure(state = "normal"))

        except Exception as e:
            self.after(0, self.hide_loading_popup)
            # Tham chiếu biến e vào biến err để sử dụng cho hàm after, vì biến e chỉ tồn tại trong phạm vi exception, còn after là ngoài exception rồi
            self.after(0, lambda err=e: messagebox.showerror("Lỗi OTP", f"Xảy ra lỗi: {str(err)}. \nHãy thử lại sau."))

    def callback_send_otp_to_user(self, to_email, success):
        """
        Thông báo gửi mã thành công tới user
        """
        logger.info("Đã gửi mã OTP tới: %s, trạng thái gửi là: %s", to_email, success)
        if success:
            self.after(0, lambda: messagebox.showinfo("Đã gửi mã OTP", "Mã OTP đã được gửi thành công. Hãy kiểm tra email. \nLưu ý mã OTP chỉ tồn tại 10 phút."))

        else:
            self.after(0, lambda: messagebox.showwarning("Lỗi khi gửi mã OTP", "Không thể gửi mã OTP đến email người dùng. Hãy thử lại."))

    def reset_passwword(self):
        """
        Chức năng đặt lại mật khẩu khi người dùng quên mật khẩu
        """
        logger.info("Sử dụng chức năng đặt lại mật khẩu")

        # Kiểm tra địa chỉ email có hợp lệ hay không
        email = self.email_account.get()
        if not self.is_valid_email(email):
            messagebox.showwarning("Cảnh báo","Địa chỉ email không hợp lệ.")
            return
        
        # Kiểm tra mã OTP đã được nhập chưa
        otp_code = self.OTP_reset.get()
        if otp_code == '':
            messagebox.showwarning("Cảnh báo","Bạn chưa nhập mã OTP!")
            return
        
        # Kiểm tra password mới có trùng nhau không
        password = self.new_password.get()
        confirm_password = self.new_password_again.get()

        if password == '' or confirm_password == '':
            messagebox.showwarning("Cảnh báo","Hãy nhập đầy đủ 2 trường thông tin mật khẩu.")
            return
        
        if password != confirm_password:
            messagebox.showwarning("Cảnh báo","Mật khẩu bạn nhập không trùng nhau, hãy kiểm tra lại!")
            return
        
        # Mở một luồng mới kiểm tra OTP và cập nhật mật khẩu mới cho người dùng
        self.show_loading_popup()
        # Tạo luồng mới để cập nhật dữ liệu vào CSDL
        threading.Thread(target=self.update_password_for_user_in_thread, args=(email, otp_code, password), daemon= True).start()

    def update_password_for_user_in_thread(self, email, otp_code, password):
        """
        Kiểm tra thông tin mật khẩu, OTP và cập nhật mật khẩu trong 1 luồng riêng
        """
        # Kiểm tra email đã tồn tại trong CSDL chưa, đã tồn tại thì mới tiến hành cập nhật mật khẩu
        check_user = self.database.get_username(email= email)

        if check_user["success"]:
            try:
                # Lấy mã OTP và thời gian hết hạn của nó
                get_otp = self.database.get_otp_and_expired_time(email= email)

                # Kiểm tra kết quả trả về
                if get_otp["success"]:

                    if get_otp["data"]:
                        otp_server = get_otp["data"][0][0]
                        expired_time_otp_server = get_otp["data"][0][1]

                        # So sánh mã OTP
                        if otp_code != otp_server:
                            self.after(0, self.hide_loading_popup)
                            self.after(0, lambda: messagebox.showwarning("Mã OTP không khớp", "Mã OTP bạn nhập không đúng. Hãy thử lại sau 10 phút."))
                            return
                        
                        # Kiểm tra xem mã OTP có hết hạn chưa
                        current_time = datetime.now()
                        if current_time > expired_time_otp_server:
                            self.after(0, self.hide_loading_popup)
                            self.after(0, lambda: messagebox.showwarning("Mã OTP hết hạn", "Mã OTP của bạn đã hết hạn. Hãy thử lại với mã OTP mới hơn."))
                            return

                        # Nếu OTP đúng và chưa hết hạn, tiến hành thay đổi mật khẩu
                        confirm_change_pw = self.database.update_password_user(email=email, password=password)

                        # Thông báo thành công
                        if confirm_change_pw["success"]:
                            self.after(0, self.hide_loading_popup)
                            self.after(0, lambda: messagebox.showinfo("Thành công", "Mật khẩu của bạn đã được cập nhật thành công!"))   

                        else:           
                            self.after(0, self.hide_loading_popup)
                            self.after(0, lambda: messagebox.showerror("Thất bại", f"{confirm_change_pw["message"]}, vui lòng thử lại."))              
                    
                    else:
                        self.after(0, self.hide_loading_popup)
                        self.after(0, lambda: messagebox.showwarning("Không có mã OTP", f"{get_otp["message"]}. Không thể cập nhật mật khẩu \nLiên hệ bộ phận IT để xử lý."))
                        return

            except Exception as e:
                logger.error("Xảy ra lỗi trong quá trình cập nhật mật khẩu cho người dùng: %s", e)

                self.after(0, self.hide_loading_popup)
                # Tham chiếu biến e vào biến err để sử dụng cho hàm after, vì biến e chỉ tồn tại trong phạm vi exception, còn after là ngoài exception rồi
                self.after(0, lambda err=e: messagebox.showerror("Lỗi đổi mật khẩu", f"Xảy ra lỗi: {str(err)}. \nHãy thử lại sau.")) 

        else:
            self.after(0, self.hide_loading_popup)
            self.after(0, lambda: messagebox.showwarning("Không thể thay đổi mật khẩu", f"{check_user["message"]} \nVui lòng thử lại sau."))
    
    def generate_random_OTP(self):
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

    def is_valid_email(self, email):
        """
        Kiểm tra tính hợp lệ của địa chỉ email bằng biểu thức chính quy.
        Trả về True hoặc False
        """
        regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        return re.match(regex, email) is not None
    
    def open_create_account_frame(self):
        """
        Tạo frame để tạo một tài khoản mới
        """
        # Xóa bỏ frame đăng nhập
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

    def create_new_account(self):
        """
        Nút bấm tạo tài khoản mới
        """
        logger.info("Sử dụng chức năng tạo tài khoản mới")
        # Kiểm tra thông tin email và mật khẩu đã được nhập chưa
        email = self.email_entry.get()
        if not self.is_valid_email(email):
            messagebox.showwarning("Cảnh báo","Địa chỉ email không hợp lệ.")
            return
        
        username = self.username_entry.get()
        password = self.password_entry.get()
        confirm_password = self.password_confirm_entry.get()

        if password == '' or username == '' or confirm_password == '':
            messagebox.showwarning("Cảnh báo","Bạn chưa nhập đầy đủ thông tin cần thiết!")
            return
        
        if password != confirm_password:
            messagebox.showwarning("Cảnh báo","Mật khẩu bạn nhập không trùng nhau, hãy kiểm tra lại!")
            return
        
        # Hiển thị popup thông báo đang tạo tài khoản mới
        self.show_loading_popup()

        # Tạo luồng mới để lưu thông tin tài khoản mới vào CSDL
        new_account = {"email": email, "username": username, "password": password}
        threading.Thread(target=self.create_new_account_login_in_thread, args=(new_account,), daemon=True).start()
        
    def create_new_account_login_in_thread(self, new_account):
        """
        Lưu thông tin tài khoản mới vào tệp cấu hình trong một luồng riêng
        """
        # Thêm thông tin người dùng mới vào CSDL
        try:
            # Kiểm tra email đã tồn tại trong CSDL chưa
            check_user = self.database.get_username(email= new_account["email"])
            # Kiểm tra kết quả trả về
            if check_user["success"]:
                if check_user["data"]:

                    # Hủy cửa sổ loading
                    self.after(0, self.hide_loading_popup)

                    # Nếu có dữ liệu trả về thì email đã tồn tại trong CSDL
                    self.after(0, lambda: messagebox.showwarning("Email đã tồn tại", f"Email {new_account['email']} đã được đăng ký. \nVui lòng sử dụng email khác."))
                    return
            else:
                # Hủy cửa sổ loading
                self.after(0, self.hide_loading_popup)
                # Nếu có lỗi xảy ra trong quá trình kiểm tra email, thông báo lỗi
                self.after(0, lambda: messagebox.showwarning("Lỗi kiểm tra email", f"Có lỗi xảy ra: {check_user['message']} \nVui lòng thử lại sau."))
                return

            # Lưu thông tin tài khoản mới vào CSDL
            create_new_user_result = self.database.create_new_user(username= new_account["username"], email= new_account["email"], password= new_account["password"])
            if create_new_user_result["success"]:
                # Gửi email thông báo đã tạo tài khoản thành công
                self.email_sender.send_email_for_new_account(to_email= new_account["email"], name= new_account["username"], website_name= self.software_name)
                # Đóng cửa sổ loading
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showinfo("Tạo tài khoản thành công", f"Bạn đã tao tài khoản thành công với email: {new_account['email']}. \nHãy đăng nhập để sử dụng phần mềm."))
                return
            else:
                # Hủy cửa sổ loading
                self.after(0, self.hide_loading_popup)
                # Nếu có lỗi xảy ra trong quá trình tạo tài khoản, thông báo lỗi    
                self.after(0, lambda: messagebox.showerror("Lỗi tạo tài khoản", f"{create_new_user_result['message']} \nVui lòng thử lại sau."))
                return

        except Exception as e:
            # Hủy cửa sổ loading
            self.after(0, self.hide_loading_popup)
            # Nếu có lỗi xảy ra trong quá trình tạo tài khoản, thông báo lỗi
            self.after(0, lambda err=e: messagebox.showerror("Lỗi tạo tài khoản", f"Xảy ra lỗi: {str(err)}. \nHãy thử lại sau."))

    def back_to_login_frame(self):
        """
        Quay trở về trang đăng nhập phần mềm
        """
        # Xóa bỏ các frame hiện tại và quay lại với login frame
        if hasattr(self, 'forgot_password_frame'):
            self.forgot_password_frame.destroy()
        if hasattr(self, 'create_account_frame'):
            self.create_account_frame.destroy()

        self.create_login_frame()

    def on_closing(self):
        """
        Nếu không đăng nhập mà đóng cửa sổ thì thực hiện đóng toàn bộ ứng dụng, tránh việc ứng dụng chính vẫn đang chạy ngầm
        """
        logger.info("Đã đóng cửa sổ đăng nhập trước khi đăng nhập vào chương trình")
        self.on_close()

    def toggle_password(self, pwd_entry: ctk.CTkEntry, show_password_var: ctk.BooleanVar):
        """
        Hiển thị mật khẩu khi người dùng chọn chức năng hiển thị mật khẩu
        """
        if show_password_var.get():
            pwd_entry.configure(show="")
        else:
            pwd_entry.configure(show="*")
    
    def login_with_google_click(self):
        """
        Chức năng đăng nhập bằng google
        """
        self.show_loading_popup()  # Hiện popup loading để báo người dùng đang xử lý

        ## start_login chạy background
        self.google_service.start_login(
            on_success=lambda info: self.after(0, lambda: self._handle_google_userinfo_with_remember(info)),
            on_error=lambda err: self.after(0, lambda: self._handle_google_login_error(err)),
            timeout_seconds=30
        )   

    def _handle_google_login_error(self, error):
        """
        UI thread xử lý lỗi khi đăng nhập bằng Google.
        """
        # Ẩn popup loading
        self.hide_loading_popup()

        # Log lỗi chi tiết để phân tích
        logger.error("Lỗi đăng nhập Google: %s", str(error))

        # Báo lỗi cho người dùng
        messagebox.showerror(
            "Lỗi đăng nhập Google",
            "Không thể đăng nhập bằng Google.\n"
            "Bạn có thể đã đóng tab đăng nhập hoặc mạng lỗi.\n\n"
            f"Chi tiết: {error}",
            parent= self
        )

    def _handle_google_userinfo_with_remember(self, user_info: dict):
        """
        Xử lý user_info Google + remember 30 ngày.
        Nếu lần đầu đăng nhập mà DB chưa có:
        - Tạo Users
        - Tạo UserExternalLogin
        - Đăng nhập như bình thường
        """
        # Đảm bảo đóng popup loading trước khi show messagebox
        self.hide_loading_popup()

        # Tách dữ liệu cần dùng từ Google
        google_id = user_info.get("sub")  # ID duy nhất của Google
        google_email = user_info.get("email")  # Email từ Google
        google_name = user_info.get("name") or google_email  # Tên hiển thị fallback

        # Kiểm tra dữ liệu bắt buộc
        if not google_email or not google_id:
            messagebox.showerror("Lỗi", "Không lấy được email/ID từ Google.", parent= self)
            return

        logger.info("Google user: %s - %s", google_email, google_name)

        # Tìm user nội bộ theo Google
        result = self.database.get_user_by_google(
            google_id=google_id,
            email=google_email
        )

        # Nếu DB báo lỗi hệ thống
        if not result.get("success"):
            messagebox.showerror("Lỗi", result.get("message", "Lỗi truy vấn DB."), parent= self)
            return

        # Lấy danh sách rows
        data = result.get("data") or []

        # =========================================================
        # NẾU CHƯA CÓ DỮ LIỆU → LẦN ĐẦU ĐĂNG NHẬP → TẠO TÀI KHOẢN MỚI
        # =========================================================
        if not data:
            # Tạo user nội bộ nếu chưa có
            create_user_res = self.database.create_user_if_not_exists_google(
                user_name=google_name,
                email=google_email
            )

            # Nếu tạo user thất bại thì thông báo
            if not create_user_res.get("success") or not create_user_res.get("data"):
                messagebox.showerror(
                    "Lỗi",
                    create_user_res.get("message", "Không thể tạo tài khoản mới."),
                    parent= self
                )
                return

            # Tạo mapping Google → Users
            link_res = self.database.link_google_login_if_not_exists(
                user_email=google_email,
                google_id=google_id,
                provider_email=google_email
            )

            # Link lỗi thì vẫn cho login tiếp, vì user nội bộ đã được tạo rồi
            # Log lại để phân tích lỗi
            if not link_res.get("success"):
                logger.warning("Link Google login thất bại: %s", link_res.get("message"))

            # Query lại để lấy row theo format usp_GetUserByGoogle
            result = self.database.get_user_by_google(
                google_id=google_id,
                email=google_email
            )

            # Nếu vẫn không lấy được
            if not result.get("success") or not result.get("data"):
                messagebox.showerror("Lỗi", "Tạo tài khoản xong nhưng không lấy lại được dữ liệu.", parent= self)
                return

            data = result["data"]

        # Lấy row đầu tiên
        row = data[0]

        # row theo usp_GetUserByGoogle:
        # User_Name, Email, IsActive, Privilege, Status, Provider, ProviderUserId, ProviderEmail
        db_email = row[1]
        is_active = row[2]
        permission = row[3]

        # Nếu user chưa active thì không cho vào hệ thống
        # Với auto-create, SP đã set IsActive=1
        if not is_active:
            messagebox.showinfo("Thông báo", "Tài khoản chưa được kích hoạt.", parent= self)
            return

        # Nếu tick remember → tạo session theo Email
        session_token = None
        if self.remember_var.get():
            s = self.database.create_session_by_email(
                email=db_email,
                days=30,
                device_info="HR Desktop App (Google)"
            )
            if s.get("success"):
                session_token = s.get("token")

        # Lưu config local
        encoded_email = base64.b64encode(db_email.encode("utf-8")).decode("utf-8")

        new_account = {
            "email": encoded_email,
            "password": None,
            "provider": "google",
            "session_token": session_token,
            "last_login_ts": datetime.now().isoformat()
        }
        self.save_or_update_account_login(new_account)

        # Cập nhật last login để audit
        self.database.update_last_login_at(db_email)

        # Đóng login window và mở main
        self.destroy()
        self.on_success(permission=permission)

    def try_auto_login_from_session(self):
        """
        Thử auto login nếu tồn tại session_token trong config.
        Quy trình:
        - Đọc danh sách account đã lưu trong file config.
        - Lọc ra các account có session_token (còn được lưu).
        - Chọn account có last_login_ts mới nhất (tài khoản đăng nhập gần nhất).
        - Gọi DB để kiểm tra session còn hạn.
        """
        accounts = self.load_account_login()  # Đọc danh sách login đã lưu (list[dict])

        if not accounts:
            return  # Không có gì trong config → bỏ qua

        # Lọc các account có session_token
        accounts_with_session = [acc for acc in accounts if acc.get("session_token")]

        if not accounts_with_session:
            # Không có account nào lưu session_token → không auto login
            return

        # Hàm phụ để parse last_login_ts
        def _parse_ts(acc):
            ts = acc.get("last_login_ts")
            if not ts:
                # Nếu account không có last_login_ts thì coi như rất cũ
                return datetime.min
            try:
                return datetime.fromisoformat(ts)
            except Exception:
                # Nếu format lỗi thì cũng coi như rất cũ
                return datetime.min

        # Chọn account có last_login_ts mới nhất
        latest_acc = max(accounts_with_session, key=_parse_ts)

        session_token = latest_acc["session_token"]  # Lấy token của account mới nhất

        logger.debug(
            "Thử auto login từ session cho email (encoded): %s, provider: %s",
            latest_acc.get("email"),
            latest_acc.get("provider")
        )

        # Hiện loading trong lúc kiểm tra session với DB
        self.show_loading_popup()

        # Hàm chạy trong luồng nền
        def _worker():
            try:
                # Gọi DB kiểm tra session còn hạn không
                result = self.database.get_user_by_session(session_token)
                # Trả kết quả về UI thread
                self.after(0, lambda r=result: self._handle_auto_login_result(r))
            except Exception as e:
                # Trả lỗi về UI thread
                self.after(0, lambda err=e: self._handle_auto_login_error(err))

        # Chạy worker ở thread nền
        threading.Thread(target=_worker, daemon=True).start()

    def _handle_auto_login_result(self, result):
        """
        Xử lý kết quả auto login.
        """
        self.hide_loading_popup()  # Luôn đóng popup

        # Nếu session không hợp lệ hoặc hết hạn
        if not result.get("success") or not result.get("data"):
            logger.info("Session auto login không hợp lệ hoặc đã hết hạn.")
            return

        row = result["data"][0]  # Lấy dòng đầu

        # row: User_Name, Email, IsActive, Privilege, Status, ExpiresAt
        is_active = row[2]
        permission = row[3]
        email = row[1]

        if not is_active:
            logger.info("User %s bị khóa/chưa kích hoạt, không auto login.", email)
            return

        logger.info("Auto login thành công cho user: %s", email)

        # Đóng login window
        self.destroy()
        # Mở app chính với permission trả về
        self.on_success(permission=permission)

    def _handle_auto_login_error(self, error):
        """
        Lỗi auto login.
        """
        self.hide_loading_popup()
        logger.error("Auto login error: %s", str(error))
        # Không cần báo lỗi UI, vì auto login là tiện ích.
        # Người dùng vẫn có thể đăng nhập tay bình thường.

    def login_with_facebook_click(self):
        """
        Click Facebook:
        - Hiện popup loading
        - Gọi service OAuth Facebook (đã tách file)
        """
        self.show_loading_popup()  # Mở loading để user thấy đang xử lý

        # Gọi service Facebook
        self.facebook_service.start_login(
            # on_success chạy trong thread service -> đưa về UI thread bằng after
            on_success=lambda info: self.after(0, lambda: self._handle_facebook_userinfo_with_remember(info)),

            # on_error -> đưa về UI thread
            on_error=lambda err: self.after(0, lambda: self._handle_facebook_login_error(err)),

            # Timeout ngắn để không treo popup nếu user đóng tab
            timeout_seconds=30
        )

    def _handle_facebook_login_error(self, error: Exception):
        """
        UI thread xử lý lỗi Facebook.
        Luôn đảm bảo đóng popup để không bị kẹt UI.
        """
        self.hide_loading_popup()  # Đóng loading

        logger.error("Lỗi đăng nhập Facebook: %s", str(error))  # Log lỗi để debug

        try:
            messagebox.showerror(
                "Lỗi đăng nhập Facebook",
                "Không thể đăng nhập bằng Facebook.\n"
                "Bạn có thể đã đóng tab đăng nhập hoặc mạng lỗi.\n\n"
                f"Chi tiết: {error}",
                parent= self
            )
        except Exception:
            # Fallback messagebox gốc
            messagebox.showerror(
                "Lỗi đăng nhập Facebook",
                "Không thể đăng nhập bằng Facebook.\n"
                "Bạn có thể đã đóng tab đăng nhập hoặc mạng lỗi.\n\n"
                f"Chi tiết: {error}",
                parent=self
            )

    def _handle_facebook_userinfo(self, user_info: dict):
        """
        Chạy trong UI thread.
        Nhiệm vụ:
        - Ẩn popup loading
        - Lấy thông tin user (id, email, name)
        - Kiểm tra user trong CSDL (get_user_by_facebook)
        - Nếu OK thì đăng nhập, lưu email+provider giống Google
        """
        # Ẩn popup loading
        self.hide_loading_popup()

        # Lấy thông tin từ Facebook
        fb_id = user_info.get("id")      # ID duy nhất của tài khoản Facebook
        fb_email = user_info.get("email")
        fb_name = user_info.get("name")

        if not fb_id:
            messagebox.showerror("Lỗi đăng nhập Facebook", "Không lấy được ID người dùng từ Facebook.")
            return

        logger.info(
            "Facebook login thành công từ phía Facebook. ID: %s, Email: %s, Name: %s",
            fb_id, fb_email, fb_name
        )

        # Gọi DB để lấy thông tin user tương ứng
        result = self.database.get_user_by_facebook(
            facebook_id=fb_id,
            email=fb_email
        )

        if not result.get("success", False):
            messagebox.showerror(
                "Lỗi đăng nhập",
                f"Lỗi khi kiểm tra tài khoản Facebook trong CSDL: {result.get('message', 'Không rõ lỗi')}"
            )
            return

        data = result.get("data")

        # Nếu chưa có user tương ứng → thông báo
        if not data:
            messagebox.showinfo(
                "Thông báo",
                f"Tài khoản Facebook {fb_email or fb_id} chưa được liên kết với hệ thống.\n"
                "Vui lòng liên hệ bộ phận IT để đăng ký / liên kết tài khoản."
            )
            return

        # Lấy record đầu tiên
        record = data[0]
        # Giả sử thứ tự cột:
        # UserId, User_Name, Email, IsActive, Privilege, Status, Provider, ProviderUserId
        db_email = record[2]
        is_active = record[3]
        permission = record[4]

        if not is_active:
            messagebox.showinfo(
                "Thông báo",
                f"Tài khoản {db_email} chưa được kích hoạt. "
                "Vui lòng liên hệ bộ phận IT để kích hoạt."
            )
            return

        logger.info(
            "Đăng nhập thành công bằng Facebook. Email: %s, Permission: %s",
            db_email, permission
        )

        # Lưu tài khoản (chỉ email + provider, không lưu mật khẩu)
        encoded_email = base64.b64encode(db_email.encode("utf-8")).decode("utf-8")
        new_account = {
            "email": encoded_email,
            "password": None,
            "provider": "facebook",
            "session_token": None,
            "last_login_ts": datetime.now().isoformat()
        }
        self.save_or_update_account_login(new_account=new_account)

        # Đóng form login, mở app chính
        self.destroy()
        self.on_success(permission=permission)
    
    def _handle_facebook_login_error(self, error: Exception):
        """
        Chạy trong UI thread, xử lý lỗi ở bước Facebook OAuth.
        """
        # Ẩn popup loading
        self.hide_loading_popup()

        # Log lỗi cho developer
        logger.error("Lỗi đăng nhập Facebook: %s", str(error))

        # Thông báo cho người dùng
        messagebox.showerror(
            "Lỗi đăng nhập Facebook",
            "Không thể đăng nhập bằng Facebook.\n"
            "Nguyên nhân có thể do:\n"
            "- Bạn hủy đăng nhập giữa chừng\n"
            "- Lỗi mạng\n"
            "- Hoặc cấu hình ứng dụng chưa đúng\n\n"
            "Vui lòng thử lại hoặc liên hệ bộ phận IT.",
            parent= self
        )
    def _handle_facebook_userinfo_with_remember(self, user_info: dict):
        """
        Xử lý user_info Facebook + remember 30 ngày.
        FULL FLOW giống Google:

        1) Nhận user_info: id, name, email (nếu Facebook trả)
        2) Tìm user nội bộ theo facebook_id/email
        3) Nếu chưa có:
        - Tạo Users
        - Link UserExternalLogin
        - Query lại
        4) Nếu tick remember:
        - create_session_by_email(30 ngày)
        5) update LastLoginAt
        6) Lưu config
        7) Đăng nhập vào app
        """
        # Đóng popup loading trước khi show messagebox
        self.hide_loading_popup()

        # Lấy dữ liệu từ Facebook
        facebook_id = user_info.get("id")                  # ID Facebook
        facebook_name = user_info.get("name")              # Tên hiển thị
        facebook_email = user_info.get("email")            # Có thể None tuỳ quyền app Facebook

        #  Kiểm tra dữ liệu bắt buộc
        if not facebook_id:
            messagebox.showerror("Lỗi", "Không lấy được ID từ Facebook.", parent= self)
            return

        # Nếu Facebook không trả email:
        #    - Bạn vẫn có thể cho tạo user theo một email "tạm"
        #    - Nhưng thực tế tốt nhất là yêu cầu quyền email từ Facebook App
        #    - Hoặc liên hệ IT để xử lý
        # Nếu thiếu email -> báo user
        if not facebook_email:
            messagebox.showerror(
                "Lỗi",
                "Facebook chưa cung cấp email cho tài khoản này.\n"
                "Vui lòng cấp quyền email hoặc liên hệ IT.",
                parent= self
            )
            return

        # Nếu không có name thì fallback bằng email
        facebook_name = facebook_name or facebook_email

        logger.info("Facebook user: %s - %s", facebook_email, facebook_name)

        # Tìm user nội bộ theo facebook
        result = self.database.get_user_by_facebook(
            facebook_id=facebook_id,
            email=facebook_email
        )

        # Nếu DB lỗi
        if not result.get("success"):
            messagebox.showerror("Lỗi", result.get("message", "Lỗi truy vấn DB."), parent= self)
            return

        data = result.get("data") or []

        # =========================================================
        # NẾU CHƯA CÓ DỮ LIỆU → TẠO TÀI KHOẢN MỚI
        # =========================================================
        if not data:
            # Tạo user nội bộ nếu chưa có
            create_user_res = self.database.create_user_if_not_exists_external(
                user_name=facebook_name,
                email=facebook_email
            )

            # Nếu tạo user thất bại
            if not create_user_res.get("success") or not create_user_res.get("data"):
                messagebox.showerror(
                    "Lỗi",
                    create_user_res.get("message", "Không thể tạo tài khoản mới."),
                    parent= self
                )
                return

            # Link Facebook → Users
            link_res = self.database.link_facebook_login_if_not_exists(
                user_email=facebook_email,
                facebook_id=facebook_id,
                provider_email=facebook_email
            )

            # Link lỗi không chặn login, nhưng log để kiểm tra
            if not link_res.get("success"):
                logger.warning("Link Facebook login thất bại: %s", link_res.get("message"))

            # Query lại để lấy row theo usp_GetUserByFacebook
            result = self.database.get_user_by_facebook(
                facebook_id=facebook_id,
                email=facebook_email
            )

            if not result.get("success") or not result.get("data"):
                messagebox.showerror("Lỗi", "Tạo tài khoản xong nhưng không lấy lại được dữ liệu.", parent= self)
                return

            data = result["data"]

        # Lấy row đầu tiên
        row = data[0]

        # row theo usp_GetUserByFacebook:
        # User_Name, Email, IsActive, Privilege, Status, Provider, ProviderUserId, ProviderEmail
        db_email = row[1]
        is_active = row[2]
        permission = row[3]

        #  Nếu user chưa active
        # Với auto-create, SP đã set IsActive=1
        if not is_active:
            messagebox.showinfo("Thông báo", "Tài khoản chưa được kích hoạt.", parent= self)
            return

        # Nếu tick remember → tạo session theo Email
        session_token = None
        if self.remember_var.get():
            s = self.database.create_session_by_email(
                email=db_email,
                days=30,
                device_info="HR Desktop App (Facebook)"
            )
            if s.get("success"):
                session_token = s.get("token")

        # Update LastLoginAt
        # Không quan trọng success/fail, nhưng nên log nếu lỗi
        upd = self.database.update_last_login_at(db_email)
        if not upd.get("success"):
            logger.warning("Update LastLoginAt thất bại: %s", upd.get("message"))

        # Lưu config local (không lưu password)
        encoded_email = base64.b64encode(db_email.encode("utf-8")).decode("utf-8")

        new_account = {
            "email": encoded_email,
            "password": None,
            "provider": "facebook",
            "session_token": session_token,
            "last_login_ts": datetime.now().isoformat()
        }
        self.save_or_update_account_login(new_account)

        # Đóng login window và mở main
        self.destroy()
        self.on_success(permission=permission)

    def check_login(self):
        """
        Đăng nhập vào phần mềm
        """
        # Lấy thông tin đăng nhập từ ô nhập
        email = self.email_login.get()
        password = self.passwd_entry.get()

        # Tài khoản test
        if email == 'test' and password == 'test':
            logger.info("Đăng nhập thành công với tài khoản test")
            encoded_password = base64.b64encode(self.passwd_entry.get().encode('utf-8')).decode('utf-8')
            encoded_email = base64.b64encode(self.email_login.get().encode('utf-8')).decode('utf-8')

            new_account = {
                "email": encoded_email,
                "password": encoded_password,
                "provider": "local_test",       # Đánh dấu provider cho dễ phân biệt
                "session_token": None,          # Không tạo session 30 ngày cho account test
                "last_login_ts": datetime.now().isoformat()
            }
            
            self.save_or_update_account_login(new_account= new_account)

            # Đóng cửa sổ này và hiển thị cửa sổ chính bằng hàm on_success và truyền vào quyền truy cập là Admin
            self.destroy()
            self.on_success(permission = "Admin")
            return
            
        if email == '' or password == '':
            messagebox.showwarning("Cảnh báo", "Bạn đang bỏ trống tên đăng nhập hoặc mật khẩu!")
            return

        # Tạo popup loading và đặt giữa chương trình
        self.show_loading_popup()

        # Tạo luồng mới để truy vấn CSDL để đăng nhập
        threading.Thread(target=self.query_database, args=(email,), daemon= True).start()
    
    def query_database(self, email):
        """
        Hàm để thực hiện truy vấn CSDL trong một luồng riêng
        """
        try:
            # Thực hiện truy vấn để lấy thông tin người dùng
            get_information_login = self.database.get_password_salt_password_privilege_user(email=email)

            # Kiểm tra kết quả trả về
            if get_information_login["success"]:
                # Đưa kết quả vào queue để lấy kết quả từ luồng chính
                self.result_queue.put(get_information_login["data"])

                # Gọi hàm để xử lý kết quả trong luồng chính
                self.after(0, self.process_login_result)
            else:
                # Đóng cửa sổ loading
                self.hide_loading_popup()
                # Nếu có lỗi xảy ra trong quá trình truy vấn, thông báo lỗi
                self.after(0, messagebox.showerror("Lỗi đăng nhập", f"{get_information_login["message"]} \nVui lòng thử lại sau."))

        except Exception as e:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            # Nếu có lỗi xảy ra trong quá trình truy vấn, thông báo lỗi
            self.after(0, lambda err=e: messagebox.showerror("Lỗi đăng nhập", f"Xảy ra lỗi: {str(err)}. \nVui lòng thử lại sau."))
    
    def process_login_result(self):
        """
        Xử lý kết quả trả về từ truy vấn CSDL
        """
        # Lấy kết quả từ queue
        data_login = self.result_queue.get()

        # Kiểm tra kết quả trả về từ CSDL
        if not data_login:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            messagebox.showinfo("Thông báo", f"Tài khoản {self.email_login.get()} chưa được đăng ký trên CSDL.", parent= self)
            return

        # Tách dữ liệu từ queue
        row = data_login[0]

        stored_hash = row[0]     # Mật khẩu đã hash trong DB
        stored_salt = row[1]     # Salt lưu trong DB
        Is_Activate   = row[2]   # Trạng thái kích hoạt là true hay false
        privilege  = row[4]      # Quyền trong hệ thống (Admin/User/...)

        # Kiểm tra xem tài khoản đã được kích hoạt chưa, hay vừa mới đăng ký
        if Is_Activate is False:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            # self.hide_loading_popup()
            messagebox.showinfo("Thông báo", f"Tài khoản {self.email_login.get()} chưa được kích hoạt, vui lòng liên hệ bộ phận IT để kích hoạt.")
            return

        # Verify mật khẩu người dùng nhập với hash + salt lưu trong DB
        input_password = self.passwd_entry.get()  # Lấy mật khẩu user vừa gõ

        check_password = Hash.verify(
            stored_salt=stored_salt,
            stored_hashed_password=stored_hash,
            input_password=input_password
        )

        if check_password:

            # Lấy thông tin email đăng nhập
            email = self.email_login.get()
            # Nếu có checkbox "Nhớ đăng nhập 30 ngày" (self.remember_var)
            session_token = None
            try:
                if getattr(self, "remember_var", None) and self.remember_var.get():
                    # Gọi DB tạo session 30 ngày cho email này
                    s = self.database.create_session_by_email(
                        email=email,
                        days=30,
                        device_info="My app Desktop App (Local)"
                    )

                    if s.get("success"):
                        session_token = s.get("token")  # Raw token trả về
                    else:
                        # Nếu tạo session lỗi thì vẫn cho login bình thường, chỉ log cảnh báo
                        logger.warning(
                            "Tạo session remember-me thất bại cho %s: %s",
                            email,
                            s.get("message")
                        )
            except Exception as ex:
                # Bất kỳ lỗi nào khi tạo session cũng không chặn login
                logger.error("Lỗi khi tạo session remember-me: %s", str(ex))

            # Cập nhật LastLoginAt trong DB (không chặn login nếu lỗi)
            try:
                upd = self.database.update_last_login_at(email)
                if not upd.get("success"):
                    logger.warning(
                        "Update LastLoginAt thất bại cho %s: %s",
                        email,
                        upd.get("message")
                    )
            except Exception as ex:
                logger.error("Lỗi update LastLoginAt: %s", str(ex))

            # Hủy cửa sổ loading
            self.hide_loading_popup()
            logger.info("Đăng nhập thành công với tài khoản: %s cùng quyền truy cập: %s", self.email_login.get(), data_login[0][3])

            # Chuẩn bị dữ liệu lưu vào file config
            #      - Mã hoá email để tránh lộ plain text (ở mức nhẹ)
            #      - Không lưu mật khẩu
            encoded_email = base64.b64encode(email.encode('utf-8')).decode('utf-8')

            new_account = {
                "email": encoded_email,
                "password": None,                   # Không lưu password nữa
                "provider": "local",                # Đánh dấu provider là local
                "session_token": session_token,     # Có thể None nếu không tick remember
                "last_login_ts": datetime.now().isoformat()  # Thời điểm đăng nhập gần nhất
            }

            # Lưu / cập nhật account trong file config
            self.save_or_update_account_login(new_account=new_account)

            # Đóng login window và mở app chính với quyền lấy từ DB
            self.destroy()
            self.on_success(permission=privilege)
        else:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            logger.warning("Đăng nhập không thành công với tài khoản: %s", self.email_login.get())
            messagebox.showinfo("Thông báo", f"Mật khẩu không chính xác, vui lòng thử lại.", parent= self)
            return
   
    def load_account_login(self):
        """
        Tải thông tin CSDL đã đăng nhập trước đây theo thứ tự thời gian đăng nhập gần nhất từ tệp JSON.
        Trả về danh sách các dict tài khoản đã lưu.
        """
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    # Đọc dữ liệu từ tệp json
                    config_data = json.load(f)
                    # Sắp xếp danh sách theo last_login_ts giảm dần
                    if 'Login' in config_data:
                        config_data['Login'].sort(
                            key=lambda acc: acc.get('last_login_ts') or '',
                            reverse=True
                        )
                # Trả về danh sách tài khoản đã sắp xếp theo thời gian đăng nhập gần nhất
                return config_data.get('Login', [])
            except Exception as e:
                # logger.error(f"Lỗi khi tải cấu hình kết nối: {e}")

                return []
        return []
    
    def save_or_update_account_login(self, new_account):
        """
        Lưu hoặc cập nhật tài khoản đăng nhập vào tệp JSON.

        - Nếu tệp chưa tồn tại → tạo mới.
        - Nếu email đã tồn tại → cập nhật (overwrite) thông tin:
            provider, session_token, last_login_ts, ...
        - Nếu email chưa tồn tại → thêm mới.

        new_account: dict tối thiểu gồm:
            {
            "email": encoded_email,
            "password": None hoặc encoded_password (nếu bạn cần),
            "provider": "local" / "google" / "facebook" / ...
            "session_token": str | None,
            "last_login_ts": isoformat datetime string
            }
        """
        config_data = {}

        # Nếu tệp cấu hình đã tồn tại → đọc vào config_data
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception as e:
                logger.error("Lỗi khi đọc file cấu hình login: %s", str(e))
                # Nếu lỗi đọc file, reset config_data để tránh crash
                config_data = {}

        # Đảm bảo luôn có key 'Login' là list
        login_list = config_data.get('Login')
        if not isinstance(login_list, list):
            login_list = []
            config_data['Login'] = login_list

        # Tìm xem email đã tồn tại trong list chưa
        existing_index = None
        for idx, acc in enumerate(login_list):
            if acc.get('email') == new_account['email']:
                existing_index = idx
                break

        if existing_index is not None:
            # Nếu đã tồn tại → cập nhật entry cũ
            logger.debug("Cập nhật tài khoản login đã tồn tại trong cấu hình.")
            login_list[existing_index] = new_account
        else:
            # Nếu chưa tồn tại → thêm mới vào cuối list
            logger.debug("Thêm tài khoản login mới vào cấu hình.")
            login_list.append(new_account)

        # Ghi lại config vào file JSON
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error("Lỗi khi lưu file cấu hình login: %s", str(e))

    def show_loading_popup(self):
        """
        Hiển thị popup với thanh tiến trình khi tải dữ liệu.
        """
        # Tạo cửa sổ Toplevel
        self.loading_popup = ctk.CTkToplevel(self,fg_color=("#3cb371", "#3cb371"))
        self.loading_popup.title("Đang tải dữ liệu...")

        # Ẩn thanh tiêu đề và các nút chức năng của cửa sổ
        self.loading_popup.overrideredirect(True)

        # Lấy tọa độ và kích thước của màn hình gốc
        self.update()
        x_main = self.winfo_x()
        y_main = self.winfo_y()
        width_main = self.winfo_width()
        height_main = self.winfo_height()

        # Đặt kích thước của màn hình loading
        width = 150
        height = 150

        x_rel = round((width_main - width)/2)
        y_rel = round((height_main - height)/2)

        x = x_rel + x_main
        y = y_rel + y_main

        # Cập nhật vị trí cửa sổ
        self.loading_popup.geometry(f'{width}x{height}+{x}+{y}')

        # Tạo label hiển thị gif
        resize_dimensions = (150,150)
        self.loading_label = LoadingGifLabel(self.loading_popup, resize=resize_dimensions)
        self.loading_label.pack(fill='both', expand=True, padx = 2, pady = 2)
        self.loading_label.load(resource_path("assets\\images\\loading\\loading_gif.gif"))

        # Khóa cửa sổ chính để chỉ có thể tương tác với cửa sổ con
        self.wm_attributes("-disabled", True)  
        self.loading_popup.grab_set()  # Vô hiệu hóa các cửa sổ khác trong khi tải
    
    def hide_loading_popup(self):
        """
        Ẩn popup khi tải xong.
        """
        self.wm_attributes("-disabled", False)  # Bật lại cửa sổ chính
        if hasattr(self, 'loading_popup'):
            # Gọi unload để giải phóng tài nguyên GIF trước khi đóng popup
            if hasattr(self.loading_label, 'unload'):
                self.loading_label.unload()
            # Destroy popup
            self.loading_popup.destroy() 

    def not_available(self):
        messagebox.showinfo("Thông báo", "Chức năng đang trong chế độ bảo trì! \nVui lòng thử lại sau.")
        return

if __name__ == "__main__":
    app = ctk.CTk()
    app.withdraw()

    def on_close():
        app.destroy()

    def on_success(permission):
        print(f"Đăng nhập thành công với quyền hạn: {permission}")
        app.destroy()

    LoginWindow(master=app, on_success= on_success, on_close= on_close)
    app.mainloop()