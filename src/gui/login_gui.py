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
from utils.resource import resource_path
from utils.send_mail import InternalEmailSender
from services.database_service import My_Database
from services.hash import Hash
from utils.loading_gif import LoadingGifLabel
from utils.constants import FILE_PATH

logger = logging.getLogger(__name__)

# Đường dẫn đến tệp chứa thông tin đăng nhập
CONFIG_FILE = FILE_PATH["LOGIN_CONFIG"]

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
            encrypted_email, encrypted_password = self.account[0]["email"], self.account[0]["password"]
            # print(email, encrypted_password)
            # Giải mã mật khẩu và email
            password = base64.b64decode(encrypted_password.encode('utf-8')).decode('utf-8')
            email = base64.b64decode(encrypted_email.encode('utf-8')).decode('utf-8')

            logger.info("Lấy thông tin đăng nhập user: %s", email)

            self.email_login.insert(0, email)
            self.passwd_entry.insert(0, password)
        else:
            self.account = None

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

        # Mở cửa sổ tạo tài khoản mới
        create_acc_btn = ctk.CTkButton(self.login_frame, text="Tạo tài khoản!", cursor="hand2", text_color="black", font=("",15),
                                fg_color= "transparent", hover_color= "#D9D9D9", anchor= "nw", command=self.open_create_account_frame)
        create_acc_btn.grid(row=4,column=0,sticky="w",pady=20,padx=20)

        # Nút đăng nhập
        login_btn = ctk.CTkButton(self.login_frame, text="Đăng nhập", font=("",15,"bold"), height=40, width=60, fg_color="#0085FF", cursor="hand2",
                        corner_radius=15, command= self.check_login)
        login_btn.grid(row=4,column=0,sticky="ne",pady=20, padx=35)

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
                    self.after(0, lambda: messagebox.showinfo("Thông báo", f"Tài khoản {email} chưa được đăng ký trên CSDL."))
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
            self.after(0, lambda: messagebox.showwarning("Đã gửi mã OTP", "Không thể gửi mã OTP đến email người dùng. Hãy thử lại."))

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
            new_account = {"email": encoded_email, "password": encoded_password}
            self.save_new_account_login(new_account= new_account)

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
        threading.Thread(target=self.query_database, args=(email, password), daemon= True).start()
    
    def query_database(self, email, password):
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
            messagebox.showinfo("Thông báo", f"Tài khoản {self.email_login.get()} chưa được đăng ký trên CSDL.")
            return

        # Kiểm tra xem tài khoản đã được kích hoạt chưa, hay vừa mới đăng ký
        if data_login[0][2] is None:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            # self.hide_loading_popup()
            messagebox.showinfo("Thông báo", f"Tài khoản {self.email_login.get()} chưa được kích hoạt, vui lòng liên hệ bộ phận IT để kích hoạt.")
            return

        # Kiểm tra mật khẩu từ CSDL
        check_password = Hash.verify(stored_salt=data_login[0][1], stored_hashed_password=data_login[0][0], input_password=self.passwd_entry.get())

        if check_password:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            logger.info("Đăng nhập thành công với tài khoản: %s cùng quyền truy cập: %s", self.email_login.get(), data_login[0][3])

            # Mã hóa mật khẩu trước khi lưu
            encoded_password = base64.b64encode(self.passwd_entry.get().encode('utf-8')).decode('utf-8')
            encoded_email = base64.b64encode(self.email_login.get().encode('utf-8')).decode('utf-8')
            new_account = {"email": encoded_email, "password": encoded_password}

            self.save_new_account_login(new_account= new_account)
            self.destroy()
            self.on_success(permission=data_login[0][3])
        else:
            # Hủy cửa sổ loading
            self.hide_loading_popup()
            logger.warning("Đăng nhập không thành công với tài khoản: %s", self.email_login.get())
            messagebox.showinfo("Thông báo", f"Mật khẩu không chính xác, vui lòng thử lại.")
            return
   
    def load_account_login(self):
        """
        Tải thông tin CSDL đã đăng nhập trước đây
        """
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                return config_data.get('Login', [])
            except Exception as e:
                # logger.error(f"Lỗi khi tải cấu hình kết nối: {e}")

                return []
        return []
    
    def save_new_account_login(self, new_account):
        """
        Lưu tài khoản đăng nhập mới vào tệp JSON
        Nếu tệp chưa tồn tại, tạo mới tệp trước khi lưu.
        Nếu tài khoản đã tồn tại, không lưu lại.
        """
        config_data = {}

        # Kiểm tra xem tệp cấu hình đã tồn tại chưa
        if os.path.exists(CONFIG_FILE):
            # Nếu tệp tồn tại, mở tệp và đọc dữ liệu
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        else:
            # Nếu tệp chưa tồn tại, tạo mới một dict cho Login
            config_data['Login'] = []

        # Kiểm tra xem email của tài khoản mới đã tồn tại trong danh sách Login chưa
        email_exists = any(account['email'] == new_account['email'] for account in config_data['Login'])
        
        if email_exists:
            logger.debug(f"Tài khoản {new_account['email']} đã tồn tại trong cấu hình, không cần lưu lại.")
            return  # Nếu tài khoản đã tồn tại, không lưu lại

        # Thêm tài khoản mới vào danh sách đăng nhập
        config_data['Login'].append(new_account)

        # Lưu dữ liệu vào tệp cấu hình
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, ensure_ascii=False, indent=4)

        # print(f"Tài khoản {new_account['email']} đã được lưu vào tệp cấu hình.")

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