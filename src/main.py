# ==============================================================================
# Author: Nguyễn Đức Quân
# Date: 2025-07-16
# Description: Cấu trúc dự án của một phần mềm máy tính xây dựng với ngôn ngữ python.
# Version: 0.0.1
# Software Name: Tên phần mềm
# Software Description: Miêu tả chi tiết về phần mềm
# Note: Một số lời nói khác
# Khi sử dụng code này, vui lòng tôn trọng chủ sở hữu bằng cách giữ nguyên phần mô tả Author, Date, Description.  
# Nếu phát hiện các lỗi liên quan đến code, vui lòng liên hệ tác giả để được hỗ trợ, hoặc bạn có thể tự sửa lỗi và đóng góp cho cộng đồng.
# Mọi hành vi sao chép, sử dụng lại code này mà không ghi rõ nguồn gốc đều không được chấp nhận.
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
import requests # pip install requests
from dataclasses import dataclass
from typing import Callable, Optional, Dict, Any, Type

# Import các frame cho navigation
from gui.login_gui import LoginWindow
from gui.home_window import HomePage
from gui.database_window import DatabasePage

# import các hàm hỗ trợ
from utils.constants import *
from utils.resource import resource_path
from logger.logger import *
from utils.check_running import check_if_running



# Tạo logging 
"""
Tạo logging để lưu lại những thông tin ra với các tham số cụ thể như: thời gian, chế độ, tên file, hàm gọi, dòng code, id và tên thread, và tin nhắn.
Lưu ý có thêm tham số: force = True bởi vì xung đột giữa các trình ghi nhật ký của các thư viện hoặc file.
Nếu đối số từ khóa này được chỉ định là True, mọi trình xử lý hiện có được gắn vào bộ ghi nhật ký gốc sẽ bị xóa và
đóng trước khi thực hiện cấu hình như được chỉ định bởi các đối số khác.
Đối với file main sẽ dùng: logger = logging.getLogger()
Còn các file khác sẽ dùng: logger = logging.getLogger(__name__) thì sẽ tự động cùng lưu vào 1 file, cùng 1 định dạng như cấu hình ở tệp main.
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

# Cấu hình mức độ ghi log
# logger.setLevel(logging.DEBUG)
logger.setLevel(logging.INFO)

# Gọi hàm kiểm tra thư mục log tồn tại bao lâu trước khi tạo thư mục mới
delete_old_logs()

# Đường dẫn tới tệp chứa thông tin cập nhật phần mềm
UPDATE_FILE = FILE_PATH["UPDATE_CONFIG"]

# Kiểm tra có tồn tại tệp tin này không trước khi đọc thông tin
if os.path.exists(UPDATE_FILE):

    # Lấy các thông tin ban đầu để khởi tạo cho phần mềm
    with open(UPDATE_FILE, 'r') as inside:
        data = json.load(inside)
        # Địa chỉ server, tên phần mềm và phiên bản hiện tại
        API_SERVER = data['Update_app']["server"]
        APP_NAME = data['Update_app']["app_name"]
        CURRENT_VERSION = data['Update_app']["current_version"]
else:
    API_SERVER = None


# Khai báo type cho lớp Frame (CustomTkinter Frame)
CTkFrameType = ctk.CTkFrame

# Tạo cấu trúc cho các mục điều hướng
@dataclass
class NavItem:
    name: str                       # Tên hiển thị (HOME_NAV / CHAT_NAV / DATABASE_NAV)
    icon_light: str                 # key ảnh light trong IMAGE[...] ở tệp constants.py
    icon_dark: str                  # key ảnh dark  trong IMAGE[...] ở tệp constants.py
    required_permissions: tuple     # quyền được phép truy cập đối với mục này
    frame_class: Optional[Type[CTkFrameType]]  # Lớp frame sẽ tạo khi cần (lazy)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Thiết lập thông tin phần mềm: Tên, icon, kích thước
        self.title(APP_NAME_SYSTEM)
        self.iconbitmap(resource_path(IMAGE["ICO_IMG"]))
        self.geometry("1600x800")
        self.withdraw() # Ẩn cửa sổ chính trước khi đăng nhập

        # Thiết lập giao diện có hàng 0 và cột thứ 1 tự động co giãn theo kích thước cửa sổ
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # Khai báo các button ở mục điều hướng bên trái, khi ấn vào sẽ hiển thị frame tương ứng bên phải
        self.nav_items: Dict[str, NavItem] = {
            HOME_NAV: NavItem(
                name=HOME_NAV,
                icon_light="HOME_NAVIGATION_LIGHT_IMG",
                icon_dark ="HOME_NAVIGATION_DARK_IMG",
                required_permissions=(PERMISSION["ADMIN"],),
                frame_class=HomePage
            ),
            CHAT_NAV: NavItem(
                name=CHAT_NAV,
                icon_light="CHAT_NAVIGATION_LIGHT_IMG",
                icon_dark ="CHAT_NAVIGATION_DARK_IMG",
                required_permissions=(PERMISSION["ADMIN"], PERMISSION["USER"], PERMISSION["GUEST"]),
                frame_class=None  # CHƯA có frame Chat -> để None (sau thêm thì nhét class vào đây)
            ),
            DATABASE_NAV: NavItem(
                name=DATABASE_NAV,
                icon_light="DATABASE_NAVIGATION_LIGHT_IMG",
                icon_dark ="DATABASE_NAVIGATION_DARK_IMG",
                required_permissions=(PERMISSION["ADMIN"], PERMISSION["USER"]),
                frame_class=DatabasePage
            ),
        }

        # Kho chứa: nút điều hướng và frame đã tạo (lazy)
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        self.frames: Dict[str, CTkFrameType] = {}   # <== chỉ tạo khi show lần đầu
        self.active_nav: Optional[str] = None       # đang chọn tab nào

        # Tạo navigation ứng dụng phía bên trái của phần mềm
        self.create_navigation()

        # Khởi tạo hàng đợi (queue) để nhận kết quả từ luồng thực thi khác
        self.data_update_queue = queue.Queue()

        # Lắng nghe sự kiện đóng cửa sổ
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # # Kiểm tra cập nhật phần mềm từ server
        # self.get_information_from_server()

        # Log thông tin khởi động ứng dụng
        logger.info ("-------------------------- Bắt đầu phiên làm việc mới --------------------------")

        # Kiểm tra định kỳ tệp ghi log 1 tiếng, nếu qua ngày mới thì chuyển tệp log sang thư mục tương ứng
        self.check_log_expire = True
        self.check_new_log()

        # Mở cửa sổ đăng nhập
        self.open_window_login()

        self.mainloop()

    def create_navigation(self):
        """
        Tạo thanh navigation bên trái sử dụng cấu hình self.nav_items.
        - Tự ẩn các nút không đủ quyền (khi đã biết self.permission)
        - Tạo icon light/dark cho từng nút
        - Gắn cùng một handler: self.show_nav(name)
        """
        # Khung chứa nav nằm bên trái chương trình
        self.navigation_frame = ctk.CTkFrame(self, corner_radius=0)
        self.navigation_frame.grid(row=0, column=0, sticky="nsew")

        # Logo / tiêu đề
        logo_image = ctk.CTkImage(Image.open(resource_path(IMAGE["NAVIGATION_LOGO_IMG"])), size=(60, 60))
        navigation_frame_label = ctk.CTkLabel(
            self.navigation_frame,
            text=f"  {APP_TITLE}",
            image=logo_image,
            compound="left",
            font=ctk.CTkFont(size=15, weight="bold")
        )
        navigation_frame_label.grid(row=0, column=0, padx=20, pady=20)

        # Dòng bắt đầu cho các nút bấm chuyển sang các tab tương ứng
        row_idx = 1

        # Tạo nút theo cấu hình
        for key, item in self.nav_items.items():

            # Icon tùy chọn theo chế độ tối và sáng
            light_img = Image.open(resource_path(IMAGE[item.icon_light]))
            dark_img  = Image.open(resource_path(IMAGE[item.icon_dark]))
            nav_icon  = ctk.CTkImage(light_image=light_img, dark_image=dark_img, size=(20, 20))

            # Tạo button
            btn = ctk.CTkButton(
                self.navigation_frame,
                corner_radius=0, height=40, border_spacing=10,
                text=item.name, image=nav_icon, anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=lambda n=item.name: self.show_nav(n)     # n là tên nav (HOME_NAV / CHAT_NAV / DATABASE_NAV) lấy từ item.name
            )

            # Chưa biết quyền vẫn render; sau login sẽ ẩn/hiện (enable/disable)
            btn.grid(row=row_idx, column=0, sticky="ew")
            self.nav_buttons[item.name] = btn
            row_idx += 1

        # Khoảng đệm đẩy option "appearance" xuống cuối
        self.navigation_frame.grid_rowconfigure(row_idx, weight=1)

        # Menu đổi theme
        self.appearance_mode_menu = ctk.CTkOptionMenu(
            self.navigation_frame, values=["Dark", "Light", "System"],
            command=self.change_appearance_mode_event
        )
        self.appearance_mode_menu.grid(row=row_idx + 1, column=0, padx=20, pady=20, sticky="s")

        # Mặc định dark
        ctk.set_appearance_mode("dark")
    
    def change_appearance_mode_event(self, new_appearance_mode):
        """
        Thay đổi chế độ sáng/tối của chương trình
        """
        ctk.set_appearance_mode(new_appearance_mode)

    def get_information_from_server(self):
        """
        Lấy thông tin phiên bản của chương trình cần được cập nhật từ phía server
        """
        if API_SERVER:
            # Kiểm tra tên phần mềm trên server và phiên bản hiện tại có cùng là 1 không
            if APP_NAME != APP_NAME_SYSTEM:
                logger.error("Tên phần mềm trên server không khớp với tên phần mềm hiện tại: %s - %s", APP_NAME, APP_NAME_SYSTEM)
                return
            
            # Đường dẫn API để kiểm tra phiên bản hiện có trên server
            LATEST_VERSION_ENDPOINT = API_SERVER + "/update/" + APP_NAME_SYSTEM + "/latest-version"
            # Tạo luồng mới để cập nhật dữ liệu vào CSDL
            threading.Thread(target=self.get_information_from_server_in_thread, args=(LATEST_VERSION_ENDPOINT,)).start()
        else:
            logger.warning(f"Không tìm thấy tệp chứa thông tin cập nhật phần mềm, khởi động phần mềm mà không kiểm tra phiên bản")

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
                
                # Lấy kết quả trả về từ API
                version_info = response.json()
                logger.debug("Truy vấn thông tin từ máy chủ thành công, nội dung phiên bản: %s", version_info)

                # Đưa dữ liệu thu được vào Queue để xử lý từ luồng chính (Không xử lý tại luồng riêng)
                self.data_update_queue.put(version_info)

                # Xử lý thông tin sau khi lấy được từ API
                self.after(0, self.check_for_updates)

            elif response.status_code == 404: # Xử lý trong trường hợp không tìm thấy tệp chứa thông tin phần mềm trên máy chủ
                error_details = response.json()["detail"]
                logger.error("Lỗi khi kiểm tra cập nhật phần mềm: %s", error_details["message"])
            
            elif response.status_code == 204:  # Xử lý trong trường hợp đọc tệp tin thất bại
                error_details = response.json()["detail"]
                logger.error("Lỗi khi kiểm tra cập nhật phần mềm: %s. %s", error_details["message"], error_details["error"])

            else:
                # Xử lý các mã trạng thái khác mà chưa lường trước được so vs 2 trường hợp đã xác định phía trên
                logger.error("Lỗi không xác định khi truy vấn API kiểm tra phiên bản phần mềm, mã trạng thái: %s", response.status_code)

        except Exception as e:
            logger.error("Không thể kết nối tới máy chủ để kiểm tra phiên bản phần mềm. Lỗi xuất hiện: %s", e)
            return
        
    def check_for_updates(self):
        """
        Nếu có bản cập nhật, khởi chạy updater và đóng ứng dụng.  
        Tệp tin chứa hông tin phiên bản trả về như sau:  
        ```
        {
            "server": "http://10.239.2.63:3838",  
            "application_name": "app_name",  
            "latest_version": "0.0.1",  
            "release_notes": "Mô tả thay đổi so với phiên bản trước",  
            "validation": 0,
            "update_for": "Admin"
        }
        ```
        """
        # Lấy thông tin từ Queue
        version_info = self.data_update_queue.get()

        if version_info:
            # Lấy thông tin phiên bản mới nhất
            latest_version = version_info.get("latest_version")
            # Lấy thông tin user (Xem những đối tượng nào cần cập nhật)
            required_user = version_info.get("update_for")
            logger.info("Phiên bản giữa server - local: %s - %s", latest_version, CURRENT_VERSION)

            # So sánh hai phiên bản để nhận diện có bản cập nhật
            if version.parse(latest_version) > version.parse(CURRENT_VERSION):

                # Nếu người đăng nhập phần mềm trùng với yêu cầu cần cập nhật thì lúc đó mới cập nhật
                if self.permission == required_user: 
                
                    # Hiển thị lời nhắc cho người dùng
                    response = messagebox.askyesno("Cập Nhật phần mềm", f"Phiên bản mới ({latest_version}) đã có.\nVui lòng tiến hành cập nhật phần mềm để tiếp tục sử dụng.")
                    
                    if response:
                        # Tiến hành chạy cập nhật chương trình khi người dùng đồng ý cập nhật
                        self.launch_updater()
                    else:
                        logger.warning("Người dùng không cập nhật phần mềm, tiến hành đóng ứng dụng")
                        # Đóng ứng dụng chính mà không hỏi
                        self.on_closing(force_close=True)

    def launch_updater(self):
        """
        Tiến hành đóng ứng dụng chính và khởi chạy phần mềm `Updater.exe` để tự động cập nhật.  
        Ứng dụng `Updater.exe` được đặt cùng vị trí với ứng dụng chính `App_name`.  
        """
        update_app_dir = os.getcwd()
        updater_path = os.path.join(update_app_dir, APP_UPDATER)
        logger.info("Khởi chạy phần mềm cập nhật tại đường dẫn: %s", updater_path)

        # Kiểm tra xem tồn tại phàn mềm updater không
        if os.path.exists(updater_path):
            # Đóng ứng dụng chính mà không hỏi
            self.on_closing(force_close=True)
            # Mở chạy phần mềm cập nhật
            subprocess.Popen([updater_path])
            
        else:
            messagebox.showerror("Không tìm thấy tệp tin", f"Không tìm thấy {APP_UPDATER}, vui lòng liên hệ bộ phận IT để cập nhật phần mềm.")
            # Đóng ứng dụng chính mà không hỏi
            self.on_closing(force_close=True)

    def check_new_log(self):
        """
        Kiểm tra xem nếu sang ngày mới thì tạo tệp log mới để lưu trữ log
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
                # Kiểm tra và thay đổi vị trí lưu tệp log
                success = change_log_file_path(logger_root=logger, new_log_file_path=None)
                
                # Nếu kết quả trả về False, có nghĩa là ko thay đổi thành công, thử lại sau 1 tiếng nữa
                if not success:
                    logger.error("Không thể thay đổi vị trí tệp log mới, tiếp tục kiểm tra sau 1 tiếng")
                
            except Exception as e:
                # Ghi log và dừng luồng
                logger.error(f"Đã gặp lỗi trong luồng kiểm tra ghi nhật ký: {e}. Dừng kiểm tra và thay đổi vị trí tệp log.")
                self.check_log_expire = False  # Dừng luồng khi gặp lỗi
                break  # Thoát khỏi vòng lặp

            # Mỗi 1 tiếng mới kiểm tra lại 1 lần
            time.sleep(3600)

    def _user_can_access(self, nav_name: str) -> bool:
        """
        Lấy ra quyền hạn của người dùng với navigation hiện tại
        """
        item = self.nav_items.get(nav_name)
        if not item:
            return False
        return getattr(self, "permission", None) in item.required_permissions

    def _ensure_frame(self, nav_name: str):
        """
        Khởi tạo frame nếu chưa có (lazy).  
        Chỉ hiển thị khi người dùng click vào nó, còn chưa click thì chưa khởi tạo
        """
        # Nếu không tồn tại navigation yêu cầu thì không cần tạo
        if nav_name in self.frames:
            return

        item = self.nav_items[nav_name]
        if item.frame_class is None:
            # Nếu chưa có UI cho mục này, tạo placeholder nhẹ để tránh lỗi
            placeholder = ctk.CTkFrame(self)
            label = ctk.CTkLabel(placeholder, text=f"{nav_name} đang được phát triển…")
            label.pack(expand=True, fill="both", padx=16, pady=16)
            self.frames[nav_name] = placeholder
        else:
            self.frames[nav_name] = item.frame_class(parent=self)  # DatabasePage(parent=self), v.v

    def _update_nav_button_colors(self, active: str):
        """Tô màu nút đang chọn, các nút khác trong suốt."""
        for name, btn in self.nav_buttons.items():
            btn.configure(fg_color=("gray75", "gray25") if name == active else "transparent")

    def show_nav(self, nav_name: str):
        """Handler duy nhất khi bấm bất kỳ nút nav nào."""
        # Kiểm tra quyền hạn người dùng
        if not self._user_can_access(nav_name):
            logger.warning("Người dùng không có quyền truy cập vào %s", nav_name)
            return self.denied_function()

        # Ẩn frame cũ nếu có
        if self.active_nav and self.active_nav in self.frames:
            self.frames[self.active_nav].grid_forget()

        # Đảm bảo frame đã tồn tại
        self._ensure_frame(nav_name)

        # Hiển thị frame
        self.frames[nav_name].grid(row=0, column=1, sticky="nsew")
        self.active_nav = nav_name
        self._update_nav_button_colors(nav_name)
        logger.info("Người dùng đã truy cập vào %s", nav_name)

    def denied_function(self):
        """
        Hiển thị popup thông báo người dùng không có quyền truy cập
        """
        messagebox.showwarning("Từ chối truy cập", "Bạn không có quyền truy cập vào chức năng này! \
                               \nVui lòng liên hệ nhà phát triển để biết thêm thông tin.")

    def on_closing(self, force_close=False):
        """
        Đóng cửa sổ khi màn hình chính đóng
        Args:
            force_close (bool): True nếu muốn đóng trực tiếp không hỏi
        """
        if force_close:
            logger.info("------------------------ Kết thúc chương trình %s ------------------------", APP_NAME_SYSTEM)
            self.destroy()
        else:
            close_app = messagebox.askokcancel("Đóng ứng dụng", "Bạn có chắc chắn muốn thoát không?")
            if close_app:
                logger.info("------------------------ Kết thúc chương trình %s ------------------------", APP_NAME_SYSTEM)
                self.destroy()
    
    def open_window_login(self):
        """
        Mở cửa sổ đăng nhập vào phần mềm
        """
        login_app = LoginWindow(self, self.login_success, self.close_login_window, software_name= APP_NAME_SYSTEM)

    def login_success(self, permission):
        """
        Sau khi đăng nhập:
        - Lưu quyền
        - Gọi kiểm tra cập nhật
        - Ẩn/hiện các nút nav theo quyền
        - Mặc định mở tab hợp lệ đầu tiên
        """
        self.deiconify()
        self.permission = permission

        # Kiểm tra cập nhật phần mềm từ server
        self.get_information_from_server()

        # Ẩn/hiện nút theo quyền
        first_allowed: Optional[str] = None
        for name, btn in self.nav_buttons.items():
            if self._user_can_access(name):
                btn.grid()  # đảm bảo hiển thị (phòng khi đã ẩn trước)
                if first_allowed is None:
                    first_allowed = name
            else:
                btn.grid_remove()  # ẩn nút không đủ quyền

        # Mặc định mở tab đầu tiên mà người dùng được vào
        if first_allowed:
            self.show_nav(first_allowed)
        else:
            # Không có quyền vào mục nào -> thoát
            self.denied_function()
            self.on_closing(force_close=True)

    def close_login_window(self):
        """
        Đóng giao diện chính khi cửa sổ đăng nhập bị hủy giữa chừng
        """
        self.destroy()

def run_app():
    exe_name = f"{APP_NAME_SYSTEM}.exe"  # Thay đổi thành tên tệp .exe của bạn

    # Kiểm tra xem phần mềm đã được mở chưa
    if check_if_running(exe_name):
        logger.warning("Ứng dụng đã được mở trước đó.")
        sys.exit()  # Thoát nếu ứng dụng đã chạy
    else:
        # Tiến hành mở giao diện phần mềm
        app = App()
# Ví dụ chạy thử:
if __name__ == "__main__":

    # Tắt hỗ trợ HIGH DPI của customtkinter, tuy nhiên nếu kích thước màn hình lớn hơn 100% khiến giao diện bị mờ
    # chức năng này tự động bật, và có thể làm co giãn kích thước theo độ phân giải màn hình, cũng gây ra lỗi chữ bé hơn trong các treeview được đặt vào frame
    # ctk.deactivate_automatic_dpi_awareness()

    # Kiểm tra xem ứng dụng đã chạy chưa, nếu đã chạy thì không mở lại
    run_app()

    # Khởi động phần mềm mà không cần kiểm tra lại
    # app = App()
