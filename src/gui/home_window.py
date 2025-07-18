import customtkinter
from tkinter import ttk, messagebox
import threading
import calendar
import queue
from PIL import Image
from itertools import count
from datetime import datetime, timedelta, date
import time
import logging
import pandas as pd  # pip install pandas

# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
import os,sys
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)

from services.database_service import My_Database

from utils.constants import *
from utils.resource import resource_path
from utils.send_mail import InternalEmailSender

from schedule_work.schedule_work import Schedule_Auto



logger = logging.getLogger(__name__)


class HomePage(customtkinter.CTkFrame):
    """
    Tạo giao diện cho trang chủ của phần mềm
    """
    def __init__(self, parent):

        # Truyền vào đối tượng của phần mềm chính
        super().__init__(parent)
        self.parent = parent

        # set grid layout 1x2
        # self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure((1,2), weight=1)

        # Khởi tạo lớp gửi email và kết nối đến CSDL
        self.email_sender = InternalEmailSender()
        self.db = My_Database() 

        # Khởi tạo hàng đợi (queue) để nhận kết quả từ luồng thực thi khác
        self.data_information_for_register_frame = queue.Queue()
        self.data_register_infor_queue= queue.Queue()
        self.data_schedule_queue= queue.Queue()
        self.data_user_queue= queue.Queue()

        # Cờ chứa giá trị để tiếp tục truy vấn lịch gửi mail sau 10 phút
        self.continue_query = True
        # cờ cho quá trình lập lịch
        self.schedule_send_mail_to_register_flag = False
        self.schedule_send_mail_leave_day_flag = False
        # Đếm số lần thử lại
        self.count_retry = 1

        self.current_time_schedule = None  # Biến lưu trữ thời gian lịch hiện tại
        self.current_date_schedule = None  # Biến lưu trữ thời gian lịch hiện tại

        self.auto_send_mail = Schedule_Auto()
        self.email_status_list = []

        # set grid layout 1x2
        # self.grid_rowconfigure(0, weight=1)
        # self.grid_columnconfigure(1, weight=1)
        # self.create_setting_register_frame(row= 0, column= 0, title= "Cấu hình chức năng gửi mail phê duyệt dữ liệu")
        # self.create_setting_leave_day_frame(row= 1, column= 0, title= "Cấu hình chức năng thông báo chưa đủ ngày nghỉ")
        # self.treeview_account = self.create_treeview_account_login_frame(row= 0, column= 1, rowspan = 2, title= "Thông tin tài khoản")
        # self.create_setting_account_login_frame(row= 0, column= 2, rowspan = 2, title= "Cài đặt tài khoản")

    def create_setting_register_frame(self, row, column, title):
        """
        Tạo frame cấu hình chức năng cho nhắc nhở phê duyệt dữ liệu
        """
        frame_configure = customtkinter.CTkFrame(self)
        frame_configure.grid(row = row, column = column, padx = 5, pady = 6, sticky = "nsew")

        title = customtkinter.CTkLabel(master= frame_configure, text= title, anchor="center", bg_color= "transparent")
        title.grid(row = 0, column = 0, padx = 5, columnspan = 2)

        title_from_mail = customtkinter.CTkLabel(master= frame_configure, text= "Mail gửi thư: ", anchor="center", bg_color= "transparent")
        title_from_mail.grid(row = 1, column = 0, padx = 5, sticky = "w")

        self.register_from_mail = customtkinter.CTkLabel(master= frame_configure, text= "Mail Send ", anchor="center", bg_color= "transparent")
        self.register_from_mail.grid(row = 1, column = 1, padx = 5, sticky = "w")

        title_time_send = customtkinter.CTkLabel(master= frame_configure, text= "Thời gian gửi: ", anchor="center", bg_color= "transparent")
        title_time_send.grid(row = 2, column = 0, padx = 5, sticky = "w")

        self.register_time_send = customtkinter.CTkLabel(master= frame_configure, text= "Time Send", anchor="center", bg_color= "transparent")
        self.register_time_send.grid(row = 2, column = 1, padx = 5, sticky = "w")

        # # Ô nhập dữ liệu test
        # self.entry_test = customtkinter.CTkEntry(frame_configure, text_color="white", placeholder_text="Nhập giá trị [(9, 30, 0)]", fg_color="black", placeholder_text_color="white",
        #                         font=("",16,"bold"), width=200, corner_radius=15, height=45)
        # self.entry_test.grid(row=4,column=0,sticky="nwe",padx=30)

        # # Tạo nút để khi nhấn sẽ lấy giá trị nhập vào và chuyển nó thành list
        # self.submit_button = customtkinter.CTkButton(
        #     frame_configure, text="Reload", command=self.check_change_time_to_send_mail  # Liên kết với hàm xử lý
        # )
        # self.submit_button.grid(row=4, column=1, padx=30, pady=10)

    def create_setting_leave_day_frame(self, row, column, title):
        """"
        Tạo frame cấu hình gửi mail tự động cho frame tính ngày nghỉ của nhân viên trong tháng
        """
        frame_configure = customtkinter.CTkFrame(self)
        frame_configure.grid(row = row, column = column, padx = 5, pady = 6, sticky = "nsew")

        title = customtkinter.CTkLabel(master= frame_configure, text= title, anchor="center", bg_color= "transparent")
        title.grid(row = 0, column = 0, padx = 5, columnspan = 2)

        title_from_mail = customtkinter.CTkLabel(master= frame_configure, text= "Mail gửi thư: ", anchor="center", bg_color= "transparent")
        title_from_mail.grid(row = 1, column = 0, padx = 5, sticky = "w")

        self.leave_day_from_mail = customtkinter.CTkLabel(master= frame_configure, text= "Mail Send ", anchor="center", bg_color= "transparent")
        self.leave_day_from_mail.grid(row = 1, column = 1, padx = 5, sticky = "w")

        title_time_send = customtkinter.CTkLabel(master= frame_configure, text= "Ngày kiểm tra: ", anchor="center", bg_color= "transparent")
        title_time_send.grid(row = 2, column = 0, padx = 5, sticky = "w")

        self.leave_day_time_send = customtkinter.CTkLabel(master= frame_configure, text= "Time Send", anchor="center", bg_color= "transparent")
        self.leave_day_time_send.grid(row = 2, column = 1, padx = 5, sticky = "w")

    def create_treeview_account_login_frame(self, row, column, rowspan, title):
        """"
        Tạo frame chứa danh sách tài khoản đăng ký trên CSDL để quản lý
        """
        frame_configure = customtkinter.CTkFrame(self)
        frame_configure.grid(row = row, rowspan = rowspan, column = column, padx = 5, pady = 6, sticky = "nsew")

        # set grid layout 1x2
        frame_configure.grid_rowconfigure(1, weight=1)
        frame_configure.grid_columnconfigure(0, weight=1)

        # Tạo tiêu đề cho bảng
        label_treeview = customtkinter.CTkLabel(frame_configure, bg_color="transparent", anchor= "center", text= title, font=customtkinter.CTkFont(size=20, weight="bold"))
        label_treeview.grid(row = 0, column = 0, columnspan = 2, sticky = "n")

        # Tạo treeview table đưa vào frame
        treeview = self.create_treeview_table(parent= frame_configure, number_value = 10)

        # Lắng nghe sự kiện click vào dòng trong Treeview
        treeview.bind("<ButtonRelease-1>", self.on_treeview_select)

        return treeview
    
    def create_treeview_table(self, parent, number_value):
        """
        Tạo treeview để hiển thị danh sách dữ liệu theo bảng
        """
        # Tạo style cho Treeview (ttk)
        style = ttk.Style()
        style.theme_use("clam")

        # Tạo style cho Treeview
        style.configure(
            "Treeview",
            background="white",
            foreground="black",
            rowheight=25,
            fieldbackground="#f0f0f0",  # Màu nền các ô trong Treeview
            bordercolor="#343638",
            borderwidth=1
        )
        style.map("Treeview", background=[('selected', '#4CAF50')])  # Màu nền khi chọn dòng

        # Đặt màu nền cho tiêu đề cột
        style.configure("Treeview.Heading",
                        background="#565b5e",  # Màu nền của tiêu đề
                        foreground="white",    # Màu chữ của tiêu đề
                        relief="flat")
        
        style.map("Treeview.Heading", background=[('active', '#3484F0')])  # Màu nền của tiêu đề khi hover
        # Thêm đường viền khi chọn dòng
        style.map("Treeview", background=[('selected', '#4CAF50')])

        # Tạo Treeview
        treeview = ttk.Treeview(
            parent,
            columns=("Tên người dùng", "Email đăng nhập", "Ngày kích hoạt", "Quyền hạn"),
            show="headings",
            height=number_value, ## Số hàng muốn hiển thị
        )
        # Tạo tên cho các cột
        treeview.heading("Tên người dùng", text="Tên người dùng")
        treeview.heading("Email đăng nhập", text="Email đăng nhập")
        treeview.heading("Ngày kích hoạt", text="Ngày kích hoạt")
        treeview.heading("Quyền hạn", text="Quyền hạn")

        # Cấu hình từng cột để tự động điều chỉnh kích thước
        # treeview.column("Code_ID", anchor="center", minwidth=40, width=120, stretch=True)
        # treeview.column("Name", anchor="center", minwidth=40, width=150, stretch=True)
        # treeview.column("Department", anchor="center", minwidth=40, width=60, stretch=True)

        # Đặt Treeview xuống hàng (row=1) để không đè tiêu đề
        treeview.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

        treeview.tag_configure('missing', foreground='red')  # Màu đỏ cho văn bản thiếu

        # Thêm scrollbar
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=treeview.yview)
        treeview.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=1, column=1, sticky="ns", pady=10)

        return treeview

    def on_treeview_select(self, event):
        """
        Xử lý sự kiện click vào dòng trong Treeview
        """
        selected_item = self.treeview_account.focus()  # Lấy ID của dòng đã chọn

        if selected_item:
            values = self.treeview_account.item(selected_item, 'values')  # Lấy giá trị của dòng đó
            self.username_user_current = values[0]  # Tên người dùng
            self.email_user_current = values[1]  # Email đăng nhập
            self.activate_user_current = values[2]  # Ngày kích hoạt
            self.role_user_current = values[3]  # Quyền hạn

            # Kích hoạt nút 'Kích hoạt tài khoản'
            self.activate_account_button.configure(state="normal")
            self.disable_account_button.configure(state="normal")
            self.delete_account_button.configure(state="normal")
            self.change_role_account_button.configure(state="normal")

    def create_setting_account_login_frame(self, row, column, rowspan, title):
        """
        Quản lý các tài khoản đăng nhập phần mềm QLNS
        """
        frame_configure = customtkinter.CTkFrame(self)
        frame_configure.grid(row = row, column = column, rowspan = rowspan, padx = 5, pady = 6, sticky = "nsew")

        # frame_configure.grid_rowconfigure(1, weight=1)
        frame_configure.grid_columnconfigure(1, weight=1)

        title = customtkinter.CTkLabel(master= frame_configure, text= title, anchor="center", bg_color= "transparent")
        title.grid(row = 0, column = 0, padx = 5, columnspan = 2)

        refresh_data= customtkinter.CTkButton(frame_configure, text="Làm mới", anchor="center",
                                                               )
        refresh_data.grid(row = 1, column = 0, padx = 5, pady = 10)

        self.activate_account_button= customtkinter.CTkButton(frame_configure, text="Kích hoạt tài khoản", anchor="center", state= "disabled", 
                                                               command= self.activate_account_user)
        self.activate_account_button.grid(row = 2, column = 0, padx = 5, pady = 10)

        self.disable_account_button= customtkinter.CTkButton(frame_configure, text="Khóa tài khoản", anchor="center", state= "disabled", 
                                                               command= lambda: self.activate_account_user(activate= False))
        self.disable_account_button.grid(row = 2, column = 1, padx = 5, pady = 10)

        self.delete_account_button= customtkinter.CTkButton(frame_configure, text="Xóa tài khoản", anchor="center", state= "disabled", fg_color="#c0392b",
                                                               command= self.delete_account_user)
        self.delete_account_button.grid(row = 3, column = 0, columnspan = 2, padx = 5, pady = 10)

        self.change_role_account_button= customtkinter.CTkButton(frame_configure, text="Thay đổi quyền", anchor="center", state= "disabled", fg_color="#b9770e",
                                                               text_color="black", command= self.change_role_user)
        self.change_role_account_button.grid(row = 4, column = 0, padx = 5, pady = 10)

        # OptionMenu hiển thị ngày
        privilege = ["Admin", "User", "GA", "HR"]
        self.optionmenue_privilege_user = customtkinter.StringVar(value=privilege[-1])
        optionmenu = customtkinter.CTkOptionMenu(
            frame_configure,
            values=privilege,
            anchor="center",
            variable=self.optionmenue_privilege_user,
            # command=self.check_select_day_filter  # Gắn callback khi thay đổi
        )
        optionmenu.grid(row=4, column=1, padx=5, pady= 10, sticky="w")

    def not_available(self):
        messagebox.showinfo("Thông báo", "Chức năng đang trong chế độ bảo trì! \nVui lòng thử lại sau.")
        return

    def first_query_for_frame_home_in_thread(self):
        """
        Truy vấn các thông tin ban đầu trong 1 luồng riêng để không gây ảnh hưởng tới giao diện chính
        """
        try:
            # Lấy thông tin mail sẽ gửi tin hằng ngày (No-Reply@terumo.co.jp)
            email_register = self.db.get_email_sender(purpose="register")
            # Dữ liệu test:
            # email_register = "No-Reply@terumo.co.jp"

            # Nếu xảy ra lỗi trong quá trình truy vấn
            if email_register is False:
                # Thay đổi cờ để dừng truy vẫn sau 10 phút 1 lần
                self.continue_query = False
                # Đóng popup
                self.after(0, self.hide_loading_popup)

                # Ghi log lại
                logger.warning("Truy vấn thông tin email người gửi của frame register tại Home xảy ra lỗi, hiển thị mặc định")

                # Tăng số lần thử lại lên 1
                self.count_retry += 1
                # Kiểm tra nếu số lần thử lại đã là 3 lần thì thông báo lỗi
                if (self.count_retry == 3):
                    self.after(0, lambda: messagebox.showerror("Lỗi kết nối", f"Không thể kết nối tới CSDL. \
                                 \n Vui lòng liên hệ bộ phận IT"))
                else:
                    # Thử lại thêm 1 lần nữa sau 1 phút      
                    if self.continue_query:
                        # Sau 1 phút thì truy vấn làm mới dữ liệu một lần, thời gian tính bằng mili giây, 1000ms = 1s
                        self.after(1000*60*1, self.first_query_for_frame_home)
                return
            
            # Lấy thông tin thời gian gửi mail hằng ngày
            time_schedule = self.db.get_time_schedule()
            # Dữ liệu test
            # time_schedule = [(25, 12, 12, 00)]
            
            # Nếu lỗi kết nối tới CSDL
            if time_schedule is False:
                # Thay đổi cờ để dừng truy vẫn sau 30 phút 1 lần
                self.continue_query = False
                # Đóng popup
                self.after(0, self.hide_loading_popup)

                # Ghi log lại
                logger.warning("Truy vấn thông tin thời gian gửi mail của frame register tại Home xảy ra lỗi, hiển thị mặc định")

                # Tăng số lần thử lại lên 1
                self.count_retry += 1
                # Kiểm tra nếu số lần thử lại đã là 3 lần thì thông báo lỗi
                if (self.count_retry == 3):
                    self.after(0, lambda: messagebox.showerror("Lỗi kết nối", f"Không thể kết nối tới CSDL. \
                                 \n Vui lòng liên hệ bộ phận IT"))
                else:
                    # Thử lại thêm 1 lần nữa sau 1 phút      
                    if self.continue_query:
                        # Sau 1 phút thì truy vấn làm mới dữ liệu một lần, thời gian tính bằng mili giây, 1000ms = 1s
                        self.after(1000*60*1, self.first_query_for_frame_home)
                return
            
            # Lấy lịch gửi mail hằng tháng
            date_schedule = self.db.get_time_schedule(status= "LeaveDay")
            # Dữ liệu test
            # date_schedule = [(25,12,12,12)]

            # Nếu lỗi kết nối tới CSDL
            if date_schedule is False:
                # Thay đổi cờ để dừng truy vẫn sau 30 phút 1 lần
                self.continue_query = False
                # Đóng popup
                self.after(0, self.hide_loading_popup)

                # Ghi log lại
                logger.warning("Truy vấn thông tin thời gian gửi mail của frame register tại Home xảy ra lỗi, hiển thị mặc định")

                # Tăng số lần thử lại lên 1
                self.count_retry += 1
                # Kiểm tra nếu số lần thử lại đã là 3 lần thì thông báo lỗi
                if (self.count_retry == 3):
                    self.after(0, lambda: messagebox.showerror("Lỗi kết nối", f"Không thể kết nối tới CSDL. \
                                 \n Vui lòng liên hệ bộ phận IT"))
                else:
                    # Thử lại thêm 1 lần nữa sau 1 phút      
                    if self.continue_query:
                        # Sau 1 phút thì truy vấn làm mới dữ liệu một lần, thời gian tính bằng mili giây, 1000ms = 1s
                        self.after(1000*60*1, self.first_query_for_frame_home)
                return

            # Đưa dữ liệu vào queue
            self.data_information_for_register_frame.put(email_register)
            self.data_information_for_register_frame.put(time_schedule)
            self.data_information_for_register_frame.put(date_schedule)

            # Nếu truy vấn thành công thì đặt số lần thử lại về ban đầu
            self.count_retry = 1

            # Sửa giao diện chương trình chính sau khi thu được dữ liệu
            self.after(0, self.process_first_information_gui)

        except Exception as e:
            self.after(0, self.hide_loading_popup)
            # Xảy ra lỗi khi truy vấn sẽ hủy gọi lại hàm này
            self.continue_query = False
            logger.error(f"Xảy ra lỗi trong lúc truy vấn thông tin ban đầu cho frame HOME: {e}")

    def activate_account_user(self, activate = True):
        """
        Nút bấm kích hoạt tài khoản người dùng để cho phép hoạt động
        """
        # Hiển popup xác nhận lại yêu cầu kích hoạt với người dùng
        result = messagebox.askokcancel("Thao tác tài khoản", f"Bạn có chắc chắn muốn kích hoạt hoặc khóa tài khoản người dùng: {self.username_user_current}")

        if result:
            logger.info("Sử dụng chức năng kích hoạt tài khoản với người dùng: %s", self.username_user_current)
            self.show_loading_popup_progress()
            # Tạo luồng mới để cập nhật dữ liệu vào CSDL
            threading.Thread(target=self.activate_account_user_in_thread, args=(activate, ), daemon= True).start()

    def activate_account_user_in_thread(self, activate):
        """
        Kích hoạt tài khoản người dùng trong 1 luồng riêng
        """
        try:
            result = self.db.activate_user(email= self.email_user_current, activate= activate)

            if result:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showinfo("Thành công", f"Tài khoản {self.username_user_current} đã được kích hoạt/ khóa tài khoản thành công"))

                # Hủy kích hoạt nút
                self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
                self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
                self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
                self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))
                logger.info("Đã kích hoạt/ khóa tài khoản: %s thành công", self.username_user_current)
            
            else:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showerror("Lỗi kết nối", "Không thể kích hoạt/ khóa tài khoản người dùng. Thử lại sau."))
                # Hủy kích hoạt nút
                self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
                self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
                self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
                self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))

        except Exception as e:
            self.after(0, self.hide_loading_popup)
            self.after(0, lambda: messagebox.showerror("Lỗi kết nối", "Không thể kích hoạt/ khóa tài khoản người dùng. Thử lại sau."))
            logger.error(f"Xảy ra lỗi trong lúc kích hoạt/ khóa tài khoản người dùng: {e}") 
            # Hủy kích hoạt nút
            self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
            self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
            self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
            self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))

    def delete_account_user(self):
        """
        Nút bấm xóa tài khoản người dùng
        """
        # Hiển popup xác nhận lại yêu cầu kích hoạt với người dùng
        result = messagebox.askokcancel("Xóa tài khoản người dùng", f"Bạn có chắc chắn muốn xóa tài khoản người dùng: {self.username_user_current}")

        if result:
            logger.info("Sử dụng chức năng xóa tài khoản với người dùng: %s", self.username_user_current)
            self.show_loading_popup_progress()
            # Tạo luồng mới để cập nhật dữ liệu vào CSDL
            threading.Thread(target=self.delete_account_user_in_thread, daemon= True).start()

    def delete_account_user_in_thread(self):
        """
        Xóa tài khoản người dùng trong luồng riêng
        """
        try:
            result = self.db.delete_account_user(email= self.email_user_current)

            if result:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showinfo("Thành công", f"Tài khoản {self.username_user_current} đã được xóa khỏi CSDL."))

                # Hủy kích hoạt nút
                self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
                self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
                self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
                self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))
            
            else:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showerror("Lỗi kết nối", "Không thể xóa tài khoản người dùng. Thử lại sau."))
                # Hủy kích hoạt nút
                self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
                self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
                self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
                self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))

        except Exception as e:
            self.after(0, self.hide_loading_popup)
            self.after(0, lambda: messagebox.showerror("Lỗi kết nối", "Không thể xóa tài khoản người dùng. Thử lại sau."))
            logger.error(f"Xảy ra lỗi trong lúc xóa tài khoản người dùng: {e}") 
            # Hủy kích hoạt nút
            self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
            self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
            self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
            self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))

    def change_role_user(self):
        """
        Nút bấm thay đổi quyền hạn người dùng
        """
        # Hiển popup xác nhận lại yêu cầu kích hoạt với người dùng
        result = messagebox.askokcancel("Thay đổi quyền hạn", f"Bạn có chắc chắn muốn thay đổi quyền hạn người dùng: {self.username_user_current}")

        if result:
            privilege = self.optionmenue_privilege_user.get()
            logger.info("Sử dụng chức năng thay đổi quyền hạn người dùng: %s", self.username_user_current)
            self.show_loading_popup_progress()
            # Tạo luồng mới để cập nhật dữ liệu vào CSDL
            threading.Thread(target=self.delete_account_user_in_thread, args=(privilege,), daemon= True).start()
        
    def delete_account_user_in_thread(self, privilege):
        """
        Thay đổi quyền hạn người dùng trong 1 luồng riêng
        """
        try:
            result = self.db.change_role_user(email= self.email_user_current, privilege= privilege)

            if result:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showinfo("Thành công", f"Đã thay đổi quyền hạn {self.username_user_current}."))

                # Hủy kích hoạt nút
                self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
                self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
                self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
                self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))
            
            else:
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showerror("Lỗi kết nối", "Không thể thay đổi quyền hạn tài khoản người dùng. Thử lại sau."))
                # Hủy kích hoạt nút
                self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
                self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
                self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
                self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))

        except Exception as e:
            self.after(0, self.hide_loading_popup)
            self.after(0, lambda: messagebox.showerror("Lỗi kết nối", "Không thể kích hoạt/ khóa tài khoản người dùng. Thử lại sau."))
            logger.error(f"Xảy ra lỗi trong lúc xóa tài khoản người dùng: {e}") 
            # Hủy kích hoạt nút
            self.after(0, lambda: self.activate_account_button.configure(state="disabled"))
            self.after(0, lambda: self.disable_account_button.configure(state="disabled"))
            self.after(0, lambda: self.delete_account_button.configure(state="disabled"))
            self.after(0, lambda: self.change_role_account_button.configure(state="disabled"))


if __name__ == "__main__":
    root = customtkinter.CTk()
    root.title("Test chức năng")
    root.geometry("1000x600")

    app_frame = HomePage(root)
    app_frame.pack(fill="both", expand=True)

    root.mainloop()
