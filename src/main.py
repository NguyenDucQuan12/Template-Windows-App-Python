# ==============================================================================
# Author: Nguyễn Đức Quân
# Date: 2025-07-16
# Description: Cấu trúc dự án của một phần mềm máy tính xây dựng với ngôn ngữ python.
# Version: 0.0.1
# Software Name: Tên phần mềm
# Software Description: Miêu tả chi tiết về phần mềm
# Note: Một số lời nói khác
# =================================================================================

import customtkinter as ctk    # pip install customtkinter
from PIL import Image  # pip install pillow           
from tkinter import messagebox
import logging
import os
import subprocess
import time
from packaging import version
import threading
import json
import queue
import requests
from utils.constants import *
from utils.resource import resource_path
from utils.logger import *



# Tạo logging 
"""
Tạo logging để lưu lại những thông tin ra với các tham số cụ thể như: thời gian, chế độ, tên file, hàm gọi, dòng code, id và tên thread, và tin nhắn.
Lưu ý có thêm tham số: force = True bởi vì xung đột giữa các trình ghi nhật ký của các thư viện hoặc file.
Nếu đối số từ khóa này được chỉ định là True, mọi trình xử lý hiện có được gắn vào bộ ghi nhật ký gốc sẽ bị xóa và
đóng trước khi thực hiện cấu hình như được chỉ định bởi các đối số khác.
Đối với file main sẽ dùng: logger = logging.getLogger()
Còn các file khác sẽ dùng: logger = logging.getLogger(__name__) thì sẽ tự động cùng lưu vào 1 file, cùng 1 định dạng nhuw tệp main.
"""

# Khởi tạo logger
logger = logging.getLogger()

# Dòng dưới sẽ ngăn chặn việc có những log không mong muốn từ thư viện PILLOW
# ví dụ: 2020-12-16 15:21:30,829 - DEBUG - PngImagePlugin - STREAM b'PLTE' 41 768
logging.getLogger("PIL.PngImagePlugin").propagate = False


# Cấu hình file log: 
logging.basicConfig(filename=log_file_path, filemode= 'a',
                    format='%(asctime)s %(levelname)s:\t %(filename)s - Line: %(lineno)d message: %(message)s',
                    datefmt='%d/%m/%Y %I:%M:%S %p', encoding = 'utf-8', force=True)

# Cấu hình logger phụ chỉ ghi message mà không có thông tin khác
logger_simplified = logging.getLogger('simplified')
handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
formatter = logging.Formatter('%(message)s')  # Chỉ ghi message
handler.setFormatter(formatter)
logger_simplified.addHandler(handler)

# Cấu hình mức độ ghi log
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

# Gọi hàm kiểm tra thư mục log tồn tại bao lâu trước khi tạo thư mục mới
delete_old_logs()

# Tệp tin chứa thông tin phần mềm và server api dùng để cập nhật phần mềm
json_filename = "data\\config.json"

# Lấy các thông tin ban đầu để khởi tạo cho phần mềm
with open(json_filename, 'r') as inside:
    data = json.load(inside)
    # Địa chỉ server, tên phần mềm và phiên bản hiện tại
    API_SERVER = data['Update_app']["server"]
    APP_NAME = data['Update_app']["app_name"]
    CURRENT_VERSION = data['Update_app']["current_version"]

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.iconbitmap(resource_path("assets\\ico\\Hr_app_logo.ico"))
        self.geometry("1600x800")
        self.withdraw() # Ẩn cửa sổ chính trước khi đăng nhập

        # set grid layout 1x2
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Tạo giao diện cho chương trình
        self.create_navigation()

        # Khởi tạo hàng đợi (queue) để nhận kết quả từ luồng thực thi khác
        self.data_update_queue = queue.Queue()

        # Lắng nghe sự kiện đóng cửa sổ
        self.protocol("WM_DELETE_WINDOW", self.on_closing)
        logger_simplified.info("——————————————————————————————————————————————————START LOG————————————————————————————————————————————————")
        logger.info("Khởi động chương trình %s", APP_NAME)

        # Kiểm tra cập nhật từ server
        self.get_information_from_server()

        # Kiểm tra định kỳ 1 tiếng 1 lần, nếu qua ngày mới thì chuyển log sang vị trí mới
        self.check_log_expire = True
        self.check_new_log()

        # Mở cửa sổ đăng nhập
        self.open_window_login()

        self.mainloop()

    def check_new_log(self):
        """
        Kiểm tra xem nếu bước sang ngày mới thì tạo tệp log mới để lưu trữ log
        """
        # Tạo luồng mới để kiểm tra định kỳ
        threading.Thread(target=self.check_new_log_in_thread, daemon= True).start()
    
    def check_new_log_in_thread(self):
        """
        Kiểm tra log trong 1 luồng riêng
        """
        while self.check_log_expire:
            try:
                logger.debug("Kiểm tra tệp log")
                # Thử thay đổi tệp log
                success = change_log_file_path(logger_root=logger, new_log_file_path=None)
                
                # Nếu kết quả trả vè False, có nghĩa là ko thay đổi thành công, thử lại sau 1 tiếng nữa
                if not success:
                    logger.error("Không thể thay đổi vị trí tệp log mới, tiếp tục kiểm tra sau 1 tiếng")
                
            except Exception as e:
                # Ghi log và dừng luồng
                logger.error(f"Đã gặp lỗi trong luồng kiểm tra tệp log: {e}. Dừng kiểm tra và thay đổi vị trí tệp log.")
                self.check_log_expire = False  # Dừng luồng khi gặp lỗi
                break  # Thoát khỏi vòng lặp

            # Mỗi 1 tiếng mới kiểm tra lại 1 lần
            time.sleep(3600)

    def get_information_from_server(self):
        """
        Lấy thông tin phiên bản của chương trình cần được cập nhật
        """
        LATEST_VERSION_ENDPOINT = API_SERVER + "/update/" + APP_NAME + "/latest-version"
        # Tạo luồng mới để cập nhật dữ liệu vào CSDL
        threading.Thread(target=self.get_information_from_server_in_thread, args=(LATEST_VERSION_ENDPOINT,)).start()

    def get_information_from_server_in_thread(self, LATEST_VERSION_ENDPOINT):
        """
        Lấy thông tin phiên bản của chương trình cần được cập nhật trong 1 luồng riêng
        """
        # Lấy thông tin phiên bản mới nhất
        try:
            # Gọi API chứa thông tin phiên bản trên server
            response = requests.get(LATEST_VERSION_ENDPOINT)

            # Kiểm tra mã trạng thái HTTP và xử lý
            if response.status_code == 200: # Nếu mã trạng thái là 200 (OK)
                
                version_info = response.json()
                logger.debug("Truy vấn thông tin từ máy chủ thành công, nội dung phiên bản: %s", version_info)
                # Đưa dữ liệu thu được vào Queue
                self.data_update_queue.put(version_info)

                # Xử lý thông tin sau khi lấy được từ API
                self.after(0, self.check_for_updates)

            elif response.status_code == 404: # Xử lý khi không tìm thấy tài nguyên trên máy chủ
                error_details = response.json()["detail"]
                logger.error("Lỗi khi gọi API: %s", error_details["message"])
            
            elif response.status_code == 204:  # Xử lý khi đọc tệp tin thất bại
                error_details = response.json()["detail"]
                logger.error("Đọc tập tin từ máy chủ thất bại. %s. %s", error_details["message"], error_details["error"])

            else:
                # Xử lý các mã trạng thái khác (với thông báo lỗi chung)
                logger.error("Lỗi không xác định khi truy vấn API, mã trạng thái: %s", response.status_code)

        except Exception as e:
            logger.error("Không thể kết nối tới máy chủ để truy vấn thông tin. Lỗi xuất hiện: %s", e)
            return
        
    def check_for_updates(self):
        """
        Kiểm tra cập nhật từ API. Nếu có bản cập nhật, khởi chạy updater và đóng ứng dụng.
        """
        # Lấy thông tin từ Queue
        version_info = self.data_update_queue.get()

        if version_info:
            # Lấy thông tin phiên bản mới nhất
            latest_version = version_info.get("latest_version")
            logger.info("Phiên bản giữa server - local: %s - %s", latest_version, CURRENT_VERSION)

            if version.parse(latest_version) > version.parse(CURRENT_VERSION):
                
                # Hiển thị lời nhắc cho người dùng
                response = messagebox.askyesno("Cập Nhật", f"Phiên bản mới ({latest_version}) đã có.\nVui lòng tiến hành cập nhật phần mềm để tiếp tục sử dụng.")
                if response:
                    self.launch_updater()
                else:
                    logger.warning("Người dùng không cập nhật phần mềm, tiến hành đóng ứng dụng")
                    # Đóng ứng dụng chính mà không hỏi
                    self.on_closing(force_close=True)

    def launch_updater(self):
        """
        Khởi chạy updater.exe và đóng ứng dụng chính.
        """
        update_app_dir = os.getcwd()
        updater_path = os.path.join(update_app_dir, "Updater.exe")
        logger.info("Khởi chạy phần mềm cập nhật tại đường dẫn: %s", updater_path)

        if os.path.exists(updater_path):
            # Đóng ứng dụng chính mà không hỏi
            self.on_closing(force_close=True)
            # Mở chạy phần mềm cập nhật
            subprocess.Popen([updater_path])
            
        else:
            messagebox.showerror("Lỗi", "Không tìm thấy Updater, vui lòng liên hệ bộ phận IT để cập nhật phần mềm.")
            # Đóng ứng dụng chính mà không hỏi
            self.on_closing(force_close=True)

    def create_navigation(self):
        """
        Tạo navigation cho chương trình
        """
        # Hình ảnh của frame navigation
        logo_image = ctk.CTkImage(Image.open(resource_path("assets\\navigation\\logo_navigation.png")), size=(60, 60))

        home_image = ctk.CTkImage(light_image=Image.open(resource_path("assets\\navigation\\home_light.png")),
                                                 dark_image=Image.open(resource_path("assets\\navigation\\home_dark.png")), size=(20, 20))
        
        canteen_image = ctk.CTkImage(light_image=Image.open(resource_path("assets\\navigation\\canteen_icon_light.png")),
                                                 dark_image=Image.open(resource_path("assets\\navigation\\canteen_icon_dark.png")), size=(20, 20))
        
        add_user_image = ctk.CTkImage(light_image=Image.open(resource_path("assets\\navigation\\add_user_light.png")),
                                                     dark_image=Image.open(resource_path("assets\\navigation\\add_user_dark.png")), size=(20, 20))
        
        leave_day_image = ctk.CTkImage(light_image=Image.open(resource_path("assets\\navigation\\leaveday_light.png")),
                                                     dark_image=Image.open(resource_path("assets\\navigation\\leaveday_dark.png")), size=(20, 20))
        # create navigation frame
        self.navigation_frame = ctk.CTkFrame(self, corner_radius=0)
        self.navigation_frame.grid(row=0, column=0, sticky="nsew")
        # Cấu hình để hàng giữa chế độ dark/light và các frame cách nhau
        self.navigation_frame.grid_rowconfigure(5, weight=1)

        # Logo và biểu tượn
        navigation_frame_label = ctk.CTkLabel(self.navigation_frame, text=f"  {APP_NAME}", image=logo_image,
                                                             compound="left", font=ctk.CTkFont(size=15, weight="bold"))
        navigation_frame_label.grid(row=0, column=0, padx=20, pady=20)

        # Frame HOME
        self.home_button = ctk.CTkButton(self.navigation_frame, corner_radius=0, height=40, border_spacing=10, text="Home",
                                                   fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                                                   image=home_image, anchor="w", command=self.home_button_event)
        self.home_button.grid(row=1, column=0, sticky="ew")

        # Frame CANTEEN
        self.canteen_button = ctk.CTkButton(self.navigation_frame, corner_radius=0, height=40, border_spacing=10, text=CANTEEN,
                                                      fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                                                      image=canteen_image, anchor="w", command=self.frame_canteen_event)
        self.canteen_button.grid(row=2, column=0, sticky="ew")

        # Frame DUYỆT DỮ LIỆU CÔNG
        self.register_frame_button = ctk.CTkButton(self.navigation_frame, corner_radius=0, height=40, border_spacing=10, text=REGISTER_FRAME,
                                                      fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                                                      image=add_user_image, anchor="w", command=self.frame_register_event)
        self.register_frame_button.grid(row=3, column=0, sticky="ew")

        # Frame TÍNH NGÀY NGHỈ
        self.leave_day_frame_button = ctk.CTkButton(self.navigation_frame, corner_radius=0, height=40, border_spacing=10, text=LEAVE_DAY_FRAME,
                                                      fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"),
                                                      image=leave_day_image, anchor="w", command=self.frame_leave_day_event)
        self.leave_day_frame_button.grid(row=4, column=0, sticky="ew")

        # Chế độ màn hình
        self.appearance_mode_menu = ctk.CTkOptionMenu(self.navigation_frame, values=["Dark", "Light", "System"],
                                                                command=self.change_appearance_mode_event)
        self.appearance_mode_menu.grid(row=7, column=0, padx=20, pady=20, sticky="s")
        # Cài đặt chế độ mặc định ban đầu là tối
        ctk.set_appearance_mode("dark")

    def create_home_page(self):
        """
        Tạo Frame Home
        """
        # create home frame
        self.home_frame = HomePage(self)

    def create_canteen_page(self):
        """
        Tạo frame cho canteen
        """
        # create second frame
        self.canteen_frame = CanteenFrame(parent= self)

    def create_register_frame(self):
        """
        Tạo frame cho duyệt dữ liệu công cho HR
        """
        # create third frame
        self.register_frame = RegisterFrame(parent= self)

    def create_leave_day_frame(self):
        """
        Tạo frame cho tính toán ngày nghỉ cho HR
        """
        # create four frame
        self.leave_day_frame = LeaveFrame(parent= self)

    def select_frame_by_name(self, name):
        """
        Hiển thị frame khi bấm vào navigation
        """
        # Cài đặt màu nút bấm khi được bấm ở navigation
        self.home_button.configure(fg_color=("gray75", "gray25") if name == "home" else "transparent")
        self.canteen_button.configure(fg_color=("gray75", "gray25") if name == CANTEEN else "transparent")
        self.register_frame_button.configure(fg_color=("gray75", "gray25") if name == REGISTER_FRAME else "transparent")
        self.leave_day_frame_button.configure(fg_color=("gray75", "gray25") if name == LEAVE_DAY_FRAME else "transparent")

        # Hiển thị frame được chọn và ẩn đi các frame khác
        if name == "home" and hasattr(self, 'home_frame'):
            self.home_frame.grid(row=0, column=1, sticky="nsew")
        else:
            if hasattr(self, 'home_frame'):
                self.home_frame.grid_forget()

        if name == CANTEEN and hasattr(self, 'canteen_frame'):
            self.canteen_frame.grid(row=0, column=1, sticky="nsew")
        else:
            if hasattr(self, 'canteen_frame'):
                self.canteen_frame.grid_forget()

        if name == REGISTER_FRAME and hasattr(self, 'register_frame'):
            self.register_frame.grid(row=0, column=1, sticky="nsew")
        else:
            if hasattr(self, 'register_frame'):
                self.register_frame.grid_forget()

        if name == LEAVE_DAY_FRAME and hasattr(self, 'leave_day_frame'):
            self.leave_day_frame.grid(row=0, column=1, sticky="nsew")
        else:
            if hasattr(self, 'leave_day_frame'):
                self.leave_day_frame.grid_forget()

    def home_button_event(self):
        """
        Xác minh quyền truy cập trước khi vào frame
        """
        # Chỉ có admin mới có quyền truy cập vào frame này
        if self.permission == "Admin":
            self.select_frame_by_name("home")
            logger.info("Đã vào trang chủ home")
        else:
            # Nếu không phải admin, thông báo không có quyền truy cập vào frame "home"
            logger.warning("Bạn không có quyền truy cập vào Home.")
            self.denied_function()

    def frame_canteen_event(self):
        """
        Xác minh quyền truy cập trước khi vào frame
        """
        # Admin, User, và GA đều có quyền truy cập vào "canteen"
        if self.permission in ["Admin", "User", "GA"]:         
            self.select_frame_by_name(CANTEEN)
            logger.info("Đã vào trang chủ %s", CANTEEN)
        else:
            # Nếu người dùng không có quyền, hiển thị thông báo lỗi
            logger.warning("Bạn không có quyền truy cập vào Canteen.")
            self.denied_function()

    def frame_register_event(self):
        """
        Xác minh quyền truy cập trước khi vào frame
        """
        # Admin, User, và HR đều có quyền truy cập vào "frame_3"
        if self.permission in ["Admin", "User", "HR"]:
            self.select_frame_by_name(REGISTER_FRAME)
            logger.info(f"Đã vào trang chủ {REGISTER_FRAME}")
        else:
            # Nếu người dùng không có quyền, hiển thị thông báo lỗi
            print(f"Bạn không có quyền truy cập vào {REGISTER_FRAME}.")
            self.denied_function()

    def frame_leave_day_event(self):
        """
        Xác minh quyền truy cập trước khi vào frame
        """
        # Admin, User, và HR đều có quyền truy cập vào "leave day"
        if self.permission in ["Admin", "User", "HR"]:
            self.select_frame_by_name(LEAVE_DAY_FRAME)
            logger.info(f"Đã vào trang chủ {LEAVE_DAY_FRAME}")
        else:
            # Nếu người dùng không có quyền, hiển thị thông báo lỗi
            print(f"Bạn không có quyền truy cập vào {LEAVE_DAY_FRAME}.")
            self.denied_function()

    def change_appearance_mode_event(self, new_appearance_mode):
        """
        Thay đổi chế độ của chương trình
        """
        ctk.set_appearance_mode(new_appearance_mode)

    def on_closing(self, force_close=False):
        """
        Đóng cửa sổ khi màn hình chính đóng
        Args:
            force_close (bool): True nếu muốn đóng trực tiếp không hỏi
        """
        if force_close:
            logger.info("Kết thúc chương trình %s", APP_NAME)
            logger_simplified.info("——————————————————————————————————————————————————END LOG————————————————————————————————————————————————")
            self.destroy()
        else:
            close_app = messagebox.askokcancel("Đóng ứng dụng", "Bạn có chắc chắn muốn thoát không?")
            if close_app:
                logger.info("Kết thúc chương trình %s", APP_NAME)
                logger_simplified.info("——————————————————————————————————————————————————END LOG————————————————————————————————————————————————")
                self.destroy()
    
    def open_window_login(self):
        """
        Mở cửa sổ đăng nhập vào CSDL
        """
        login_app = LoginWindow(self, self.login_success, self.close_login_window, software_name= APP_NAME)

    def login_success(self, permission):
        """
        Nếu đăng nhập thành công thì mở lại giao diện chính và phân quyền truy cập các frame.
        """
        self.deiconify()
        self.permission = permission
        
        # Kiểm tra quyền truy cập của người dùng và mở các frame tương ứng với quyền đó
        if permission == "Admin":
            self.create_home_page()
            self.create_canteen_page()
            self.create_register_frame()
            self.create_leave_day_frame()
            self.select_frame_by_name("home")

        elif permission == "HR":
            self.create_register_frame()
            self.create_leave_day_frame()
            self.select_frame_by_name(REGISTER_FRAME)

        elif permission == "GA":
            self.create_canteen_page()
            self.select_frame_by_name(CANTEEN)

        elif permission == "User":
            self.create_canteen_page()
            self.create_register_frame()
            self.create_leave_day_frame()
            self.select_frame_by_name(CANTEEN)
        
        else:
            self.denied_function()
            self.on_closing()

    def close_login_window(self):
        """
        Đóng giao diện chính khi cửa sổ đăng nhập bị hủy
        """
        self.destroy()

    def denied_function(self):
        messagebox.showwarning("Từ chối truy cập", "Bạn không có quyền truy cập vào chức năng này! \
                               \nVui lòng liên hệ nhà phát triển để biết thêm thông tin.")

# Ví dụ chạy thử:
if __name__ == "__main__":
    app = App()
