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
from utils.loading_gif import LoadingGifLabel
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
        self.grid_columnconfigure(0, weight=1)

        # Khởi tạo lớp gửi email và kết nối đến CSDL
        self.email_sender = InternalEmailSender()
        self.db = My_Database() 

        # Khởi tạo hàng đợi (queue) để nhận kết quả từ luồng thực thi khác
        self.data_user_queue= queue.Queue()

        # Đếm số lần thử lại
        self.count_retry = 1

        self.current_time_schedule = None  # Biến lưu trữ thời gian lịch hiện tại
        self.current_date_schedule = None  # Biến lưu trữ thời gian lịch hiện tại

        self.auto_send_mail = Schedule_Auto()
        self.email_status_list = []

        # set grid layout 1x2
        # self.grid_rowconfigure(0, weight=1)
        # self.grid_columnconfigure(1, weight=1)
        self.treeview_account = self.create_treeview_account_login_frame(row= 0, column= 0, rowspan = 2, title= "Thông tin tài khoản")
        self.create_setting_account_login_frame(row= 0, column= 1, rowspan = 2, title= "Cài đặt tài khoản")

    def create_treeview_account_login_frame(self, row, column, rowspan = 1, columnspan = 1, title = "Tiêu đề của bảng"):
        """"
        Tạo frame bao gồm hàng đầu tiên là tiêu đề và hàng thứ hai là Treeview để hiển thị danh sách 
        """
        # Tạo frame để chứa Treeview và tiêu đề
        # row, column, rowspan, columnspan: vị trí của frame trong grid layout
        frame_configure = customtkinter.CTkFrame(self)
        frame_configure.grid(row = row, rowspan = rowspan, column = column, columnspan = columnspan, padx = 5, pady = 6, sticky = "nsew")

        # Thiết lập cấu hình cho frame
        # Hàng đầu tiên là tiêu đề không cần kéo dãn, bắt buộc hàng thứ hai là Treeview sẽ kéo dãn theo kích thước của frame
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

        # Cấu hình màu sắc cho Treeview
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

            # Kích hoạt các nút bấm
            self.activate_account_button.configure(state="normal")
            self.disable_account_button.configure(state="normal")
            self.delete_account_button.configure(state="normal")
            self.change_role_account_button.configure(state="normal")

    def create_setting_account_login_frame(self, row, column, rowspan, title):
        """
        Quản lý các tài khoản đăng nhập phần mềm
        """
        frame_configure = customtkinter.CTkFrame(self)
        frame_configure.grid(row = row, column = column, rowspan = rowspan, padx = 5, pady = 6, sticky = "nsew")

        # frame_configure.grid_rowconfigure(1, weight=1)
        frame_configure.grid_columnconfigure(1, weight=1)

        title = customtkinter.CTkLabel(master= frame_configure, text= title, anchor="center", bg_color= "transparent")
        title.grid(row = 0, column = 0, padx = 5, columnspan = 2)

        refresh_data= customtkinter.CTkButton(frame_configure, text="Làm mới", anchor="center", command= self.refresh_infor_all_user)
        refresh_data.grid(row = 1, column = 0, padx = 5, pady = 10)

        self.activate_account_button= customtkinter.CTkButton(frame_configure, text="Kích hoạt tài khoản", anchor="center", state= "disabled", 
                                                               command= self.activate_account_user)
        self.activate_account_button.grid(row = 2, column = 0, padx = 5, pady = 10)

        self.disable_account_button= customtkinter.CTkButton(frame_configure, text="Khóa tài khoản", anchor="center", state= "disabled", 
                                                               command= lambda: self.activate_account_user(activate= False))
        self.disable_account_button.grid(row = 2, column = 1, padx = 5, pady = 10)

        self.delete_account_button= customtkinter.CTkButton(frame_configure, text="Xóa tài khoản", anchor="center", state= "disabled", fg_color= COLOR["DANGER_BUTTON_COLOR"],
                                                               command= self.delete_account_user)
        self.delete_account_button.grid(row = 3, column = 0, columnspan = 2, padx = 5, pady = 10)

        self.change_role_account_button= customtkinter.CTkButton(frame_configure, text="Thay đổi quyền", anchor="center", state= "disabled", fg_color="#b9770e",
                                                               text_color="black", command= self.change_role_user)
        self.change_role_account_button.grid(row = 4, column = 0, padx = 5, pady = 10)

        # input để nhập đổi mật khẩu
        self.input_change_password = customtkinter.CTkEntry(frame_configure, placeholder_text="Nhập mật khẩu mới", show="*", width= 150)
        self.input_change_password.grid(row=5, column=0, padx=5, pady=10, sticky="w")
        # input để nhập lại mật khẩu
        self.input_change_password_again = customtkinter.CTkEntry(frame_configure, placeholder_text="Nhập lại mật khẩu mới", show="*", width= 150)
        self.input_change_password_again.grid(row=5, column=1, padx=5, pady=10, sticky="w")

        self.change_password_account_button= customtkinter.CTkButton(frame_configure, text="Đổi mật khẩu", anchor="center", state= "disabled", fg_color=COLOR["WARNING_BUTTON_COLOR"],
                                                               text_color="black", command= self.change_role_user)
        self.change_password_account_button.grid(row = 6, column = 0, columnspan = 2, padx = 5, pady = 10)

        # OptionMenu hiển thị danh sách quyền hạn người dùng
        self.optionmenue_privilege_user = customtkinter.StringVar(value=LIST_PERMISSION[-1])
        optionmenu = customtkinter.CTkOptionMenu(
            frame_configure,
            values=LIST_PERMISSION,
            anchor="center",
            variable=self.optionmenue_privilege_user,
            # command=self.check_select_day_filter  # Gắn callback khi thay đổi
        )
        optionmenu.grid(row=4, column=1, padx=5, pady= 10, sticky="w")

    def not_available(self):
        messagebox.showinfo("Thông báo", "Chức năng đang trong chế độ bảo trì! \nVui lòng thử lại sau.")
        return
    
    def refresh_infor_all_user(self):
        """
        Nút bấm lấy thông tin tài khoản người dùng và hiển thị lên treeview
        """
        # Hiện popup loading
        self.show_loading_popup()

        # Tạo luồng mới để cập nhật dữ liệu vào CSDL
        threading.Thread(target=self.get_all_infor_user_in_thread, daemon= True).start()
    
    def get_all_infor_user_in_thread(self):
        """
        Truy vấn thông tin người dùng trong một luồng riêng
        """
        try:
            results = self.db.get_information_all_user()
            
            # Nếu là False thì sẽ là lỗi trong khi truy vấn
            if results["success"] is False:
                # Đóng popup và hiển thị messagebox
                self.after(0, self.hide_loading_popup)
                self.after(0, lambda: messagebox.showerror("Lỗi truy vấn", "Không thể truy vấn dữ liệu người dùng từ CSDL."))
                return
            
            # Đưa dữ liệu vào Queue để xử lý
            self.data_user_queue.put(results["data"])
            # Gọi hàm xử lý giao diện chính
            self.after(0, self.process_data_all_user)

        except Exception as e:
            self.after(0, self.hide_loading_popup)
            self.after(0, lambda err=e: messagebox.showerror("Lỗi truy vấn", f"Xảy ra lỗi: {str(err)}. \nVui lòng thử lại sau."))
            logger.error(f"Xảy ra lỗi trong lúc truy vấn thông tin người dùng từ CSDL: {e}")

    def process_data_all_user(self):
        """
        Hiển thị dữ liệu từ người dùng lên treeview
        """
        data = self.data_user_queue.get()
        
        if data:
            # List lưu trữ dữ liệu sau khi đã xử lý
            processed_rows = []
            # Duyệt qua từng hàng dữ liệu
            for i, row in enumerate(data):
                processed_row = []  # Danh sách mới để lưu giá trị đã xử lý cho mỗi hàng

                # Xử lý các giá trị cho mỗi cột trong row
                # for index, value in enumerate(row):
                #     # Kiểm tra và thay thế giá trị None cho cột "Bo Phan"
                #     if TABLE_COLUMN_LIST_EMPLOYEE_REGISTER[index] == "Bo Phan" and value is None:
                #         processed_row.append("JP")  # Thay thế None ở cột "BoPhan" bằng "JP"
                #     # Kiểm tra và thay thế giá trị None cho các cột khác
                #     # elif value is None:
                #     #     processed_row.append(0)  # Thay thế None ở các cột khác bằng 0
                #     else:
                #         processed_row.append(value)  # Nếu không phải None, giữ nguyên giá trị

                # Thêm hàng đã xử lý vào danh sách processed_rows
                processed_rows.append(tuple(processed_row))  # Thêm processed_row dưới dạng tuple vào processed_rows
        
            # Hiển thị dữ liệu lên treeview
            self.insert_data_to_treeview(treeview= self.treeview_account, data= data, column_data= ACCOUNT_TABLE_COLUMN_LIST)

            # Đóng các nút thao tác
            self.activate_account_button.configure(state="disabled")
            self.disable_account_button.configure(state="disabled")
            self.delete_account_button.configure(state="disabled")
            self.change_role_account_button.configure(state="disabled")
            
            # Đóng popup
            self.hide_loading_popup()
        else:
            # Nếu không có dữ liệu thì hiển thị thông báo
            self.hide_loading_popup()
            messagebox.showwarning("Không có dữ liệu", "Không tìm thấy dữ liệu về người dùng.")
            
            return
        
    def insert_data_to_treeview(self, treeview: ttk.Treeview, data:list, column_data: list):
        """
        Hiển thị dữ liệu lên treeview tương ứng với dữ liệu thô thu đươc từ CSDL
        """
        # Đặt tiêu đề cột cho Treeview
        treeview["columns"] = column_data  # Cập nhật các cột trong Treeview
        for col in column_data:
            treeview.heading(col, text=col)
            treeview.column(col, width=50, anchor="center", stretch=True)  # Cấu hình chiều rộng cột

        # Xóa các hàng cũ trong Treeview
        for row in treeview.get_children():
            treeview.delete(row)

        # Chèn dữ liệu từ cơ sở dữ liệu vào Treeview
        number_data = len(data)
        for i, row in enumerate(data):

            row_tag = ''  # Mặc định không có tag
            for value in row:
                if value is None:  # Kiểm tra nếu giá trị là None trong từng dòng dữ liệu
                    row_tag = 'missing'  # Gán tag 'missing' cho dòng này

            # Chèn dữ liệu từng dòng vào tương ứng với từng cột trong treeview
            treeview.insert("", "end", values=list(row), tags=(row_tag,))

    def activate_account_user(self, activate = True):
        """
        Nút bấm kích hoạt tài khoản người dùng để cho phép hoạt động
        """
        # Hiển popup xác nhận lại yêu cầu kích hoạt với người dùng
        result = messagebox.askokcancel("Thao tác tài khoản", f"Bạn có chắc chắn muốn kích hoạt hoặc khóa tài khoản người dùng: {self.username_user_current}")

        if result:
            logger.info("Sử dụng chức năng kích hoạt tài khoản với người dùng: %s", self.username_user_current)
            self.show_loading_popup()
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
            self.show_loading_popup()
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
            self.show_loading_popup()
            # Tạo luồng mới để cập nhật dữ liệu vào CSDL
            threading.Thread(target=self.change_role_user_in_thread, args=(privilege,), daemon= True).start()

    def change_role_user_in_thread(self, privilege):
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

    def show_loading_popup(self):
        """
        Hiển thị popup với thanh tiến trình khi tải dữ liệu.
        """
        # Tạo cửa sổ Toplevel
        self.loading_popup = customtkinter.CTkToplevel(self,fg_color=("#3cb371", "#3cb371"))
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
        self.parent.wm_attributes("-disabled", True)  
        self.loading_popup.grab_set()  # Vô hiệu hóa các cửa sổ khác trong khi tải
    
    def hide_loading_popup(self):
        """
        Ẩn popup khi tải xong.
        """
        self.parent.wm_attributes("-disabled", False)  # Bật lại cửa sổ chính
        if hasattr(self, 'loading_popup'):
            # Gọi unload để giải phóng tài nguyên GIF trước khi đóng popup
            if hasattr(self.loading_label, 'unload'):
                self.loading_label.unload()
            # Destroy popup
            self.loading_popup.destroy() 


if __name__ == "__main__":
    root = customtkinter.CTk()
    root.title("Test chức năng")
    root.geometry("1000x600")

    app_frame = HomePage(root)
    app_frame.pack(fill="both", expand=True)

    root.mainloop()
