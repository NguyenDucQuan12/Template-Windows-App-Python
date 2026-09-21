"""
==============================================================================
Author: Nguyễn Đức Quân
Date: 2025-07-16
Description: Cấu trúc dự án của một phần mềm máy tính xây dựng với ngôn ngữ python.
Version: 0.0.1
Software Name: Tên phần mềm
Software Description: Miêu tả chi tiết về phần mềm
Note: Một số lời nói khác
Khi sử dụng code này, vui lòng tôn trọng chủ sở hữu bằng cách giữ nguyên phần mô tả Author, Date, Description.  
Nếu phát hiện các lỗi liên quan đến code, vui lòng liên hệ tác giả để được hỗ trợ, hoặc bạn có thể tự sửa lỗi và đóng góp cho cộng đồng.
Mọi hành vi sao chép, sử dụng lại code này mà không ghi rõ nguồn gốc đều không được chấp nhận. Tác giả sẽ rất tức giận và không làm gì.
=================================================================================
"""
from typing import Optional, Dict, Type
import logging
from dataclasses import dataclass
import os
import threading
import json
import queue
import subprocess
import sys
import multiprocessing
from pathlib import Path
from tkinter import TclError
from tkinter import messagebox
import customtkinter as ctk    # pip install customtkinter
from PIL import Image  # pip install pillow
import pystray  # pip install pystray
from pystray import MenuItem
from packaging import version
import requests # pip install requests

# Import các frame cho navigation
from gui.login_gui import LoginWindow
from utils.secure_session_store import SessionStore, StoreError
from services.auth_adapter import DatabaseAuthAdapter, AuthSession
from gui.home_window import HomePage
from gui.database_window import DatabasePage

# import các hàm hỗ trợ
from utils.constants import APP_NAME_SYSTEM, APP_TITLE, FILE_PATH, IMAGE, APP_UPDATER, HOME_NAV, CHAT_NAV, DATABASE_NAV, LOGOUT_NAV, PERMISSION
from utils.check_running import single_instance, AlreadyRunningError
from utils.resource import resource_path
from logger.logger import change_log_file_path, delete_old_logs, log_file_path

# pylint: disable=pointless-string-statement
"""
Tạo logging để lưu lại những thông tin ra với các tham số cụ thể như: thời gian, chế độ, tên file, hàm gọi, dòng code, id và tên thread, và tin nhắn.
Lưu ý có thêm tham số: force = True bởi vì xung đột giữa các trình ghi nhật ký của các thư viện hoặc file.
Nếu đối số từ khóa này được chỉ định là True, mọi trình xử lý hiện có được gắn vào bộ ghi nhật ký gốc sẽ bị xóa và
đóng trước khi thực hiện cấu hình như được chỉ định bởi các đối số khác.
Đối với file main sẽ dùng: logger = logging.getLogger()
Còn các file khác sẽ dùng: logger = logging.getLogger(__name__) thì sẽ tự động cùng lưu vào 1 file, cùng 1 định dạng như cấu hình ở tệp main.
"""
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
# Đọc thông tin cập nhật phần mềm từ tệp JSON nếu tồn tại
APP_NAME = ""
CURRENT_VERSION = ""
API_SERVER = None
try:
    if os.path.exists(UPDATE_FILE):
        with open(UPDATE_FILE, encoding="utf-8") as inside:
            update_config = json.load(inside)["Update_app"]
        APP_NAME = update_config["app_name"]
        CURRENT_VERSION = update_config["current_version"]
        API_SERVER = update_config["server"]
        if not all(isinstance(value, str) for value in (APP_NAME, CURRENT_VERSION, API_SERVER)):
            raise ValueError("Cấu hình cập nhật phải chứa chuỗi")
except (OSError, ValueError, KeyError, TypeError):
    API_SERVER = None
    logger.exception("Cấu hình cập nhật không hợp lệ; bỏ qua kiểm tra cập nhật")

# Khai báo type cho lớp Frame (CustomTkinter Frame)
CTkFrameType = ctk.CTkFrame
# Tạo cấu trúc cho các mục điều hướng
@dataclass
class NavItem:
    """
    Cấu trúc dữ liệu cho các mục điều hướng trong ứng dụng  
    Attributes:  
    - name: Tên hiển thị của mục điều hướng (ví dụ: "Trang chủ", "Trò chuyện", "Cơ sở dữ liệu")
    - icon_light: Tên khóa của ảnh icon chế độ sáng trong IMAGE[...] ở tệp constants.py
    - icon_dark: Tên khóa của ảnh icon chế độ tối trong IMAGE[...] ở tệp constants.py
    - required_permissions: Tuple chứa các quyền được phép truy cập đối với mục này (ví dụ: ("Admin", "User"))
    - frame_class: Lớp frame sẽ được tạo khi cần (lazy loading). Nếu chưa có frame, có thể để None.
    """
    name: str
    icon_light: str
    icon_dark: str
    required_permissions: tuple
    frame_class: Optional[Type[CTkFrameType]]
class App(ctk.CTk):
    """
    Lớp chính của ứng dụng, kế thừa từ ctk.CTk (CustomTkinter)
    Chứa các phương thức và thuộc tính để quản lý giao diện, điều hướng, đăng nhập, và cập nhật phần mềm.
    """
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
        self.logout_items: Dict[str, NavItem] = {
            LOGOUT_NAV: NavItem(
                name=LOGOUT_NAV,
                icon_light="LOGOUT_LIGHT_IMG",
                icon_dark="LOGOUT_DARK_IMG",
                required_permissions=(PERMISSION["ADMIN"], PERMISSION["USER"], PERMISSION["GUEST"]),
                frame_class=None  # Logout không có frame
            ),
        }
        # Kho chứa: nút điều hướng và frame đã tạo (lazy)
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        self.frames: Dict[str, CTkFrameType] = {}   # <== chỉ tạo khi show lần đầu
        self.active_nav: Optional[str] = None       # đang chọn tab nào
        self.permission = None                # quyền hạn hiện tại của người dùng (Admin / User / Guest)
        self.current_auth = None
        self.current_session_token = None
        self._allow_auto_login = True
        self.auth_adapter = DatabaseAuthAdapter()
        try:
            self.session_store = SessionStore()
        except StoreError:
            self.session_store = None
        self._closing = False
        self._logout_in_progress = False
        self._login_generation = 0
        self._login_pending = False
        self._login_window = None
        self._ui_queue = queue.Queue()
        self._poll_id = None
        self._stop_event = threading.Event()
        self._tray_ready = threading.Event()
        self._tray_lock = threading.Lock()
        self._tray_thread = None
        self._update_thread = None
        self._log_thread = None
        self.tray_icon = None

        # Tạo navigation ứng dụng phía bên trái của phần mềm
        self.create_navigation()
        # Khởi tạo hàng đợi (queue) để nhận kết quả từ luồng thực thi khác
        self.data_update_queue = queue.Queue()

        # Lắng nghe sự kiện đóng cửa sổ
        self.protocol("WM_DELETE_WINDOW", self.hide_window)

        # # Kiểm tra cập nhật phần mềm từ server
        # self.get_information_from_server()
        # Log thông tin khởi động ứng dụng
        logger.info ("-------------------------- Bắt đầu phiên làm việc mới --------------------------")
        # Kiểm tra định kỳ tệp ghi log 1 tiếng, nếu qua ngày mới thì chuyển tệp log sang thư mục tương ứng
        self.check_log_expire = True
        self.check_new_log()

        # Kiểm tra danh sách nhiệm vụ nếu có trong Queue
        self._poll_ui_queue()
        # Mở cửa sổ đăng nhập
        self.open_window_login()

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
        for _, item in self.nav_items.items():
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

        # ---------- Tạo nút Đăng xuất ở gần đáy ----------
        logout_item = self.logout_items[LOGOUT_NAV]
        if logout_item:
            light_img = Image.open(resource_path(IMAGE[logout_item.icon_light]))
            dark_img  = Image.open(resource_path(IMAGE[logout_item.icon_dark]))
            logout_icon = ctk.CTkImage(light_image=light_img, dark_image=dark_img, size=(20, 20))
            self.logout_button = ctk.CTkButton(
                self.navigation_frame,
                corner_radius=0, height=40, border_spacing=10,
                text=LOGOUT_NAV, image=logout_icon, anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray70", "gray30"),
                command=self.logout                        # gọi thẳng hàm logout
            )
            # Đặt ở dưới spacer
            self.logout_button.grid(row=row_idx + 1, column=0, sticky="ew")
            # self.nav_buttons[LOGOUT_NAV] = self.logout_button     # Không thêm vào nav_buttons vì ko cần highlight, và khi duyệt nav ko cần check quyền, ai cũng có thể thấy

        # Menu đổi theme
        self.appearance_mode_menu = ctk.CTkOptionMenu(
            self.navigation_frame, values=["Dark", "Light", "System"],
            command=self.change_appearance_mode_event
        )
        self.appearance_mode_menu.grid(row=row_idx + 2, column=0, padx=20, pady=20, sticky="s")

        # Mặc định dark
        ctk.set_appearance_mode("dark")

    def change_appearance_mode_event(self, new_appearance_mode):
        """
        Thay đổi chế độ sáng/tối của chương trình
        """
        ctk.set_appearance_mode(new_appearance_mode)

    def logout(self, forget_device: bool = True):
        """
        Đổi tài khoản trong cùng App; tray thuộc ứng dụng, không thuộc user.
        - forget_device: nếu True thì xóa session_token trong config để lần sau không auto login nữa
        """
        if self._closing or self._logout_in_progress or self.permission is None:
            return

        self._logout_in_progress = True
        try:
            if not messagebox.askyesno("Đăng xuất", "Đăng xuất và bỏ ghi nhớ tài khoản trên máy này?", parent=self):
                return
            # Xóa local trước; không để tài khoản cũ tự đăng nhập khi đổi user.
            if forget_device:
                try:
                    if self.session_store is not None:
                        self.session_store.clear()
                        # Nhớ thêm bước xóa token ở trên DB
                except StoreError:
                    messagebox.showerror("Đăng xuất", "Không xóa được phiên đã lưu. Kiểm tra quyền thư mục trước khi tiếp tục.", parent=self)
                    return

            # Đưa các giá trị về mặc định
            token = self.current_auth.token if self.current_auth else None
            # Tăng generation để hủy các luồng đang chạy liên quan đến phiên cũ, xóa quyền hạn
            self._login_generation += 1
            self._allow_auto_login = False
            self.permission = None
            self.current_auth = None
            self.current_session_token = None

            # Ẩn cửa sổ chính, xóa các frame và ẩn các nút nav
            self.withdraw()
            self._clear_session_frames()
            for button in self.nav_buttons.values():
                button.grid_remove()

            # Mở lại cửa sổ đăng nhập
            self.open_window_login()
            if token:
                def revoke():
                    """
                    Thu hồi token
                    """
                    success = self.auth_adapter.revoke(token)
                    if not self._stop_event.is_set():
                        self._ui_queue.put(("logout_revoke", success))

                threading.Thread(target=revoke, daemon=True, name="LogoutRevoke").start()
        finally:
            self._logout_in_progress = False

    def _clear_session_frames(self):
        """
        cleanup() của từng Page phải dừng worker/timer trước khi destroy.
        """
        # Lấy danh sách frame hiện có, xóa khỏi self.frames để tránh callback sau khi destroy
        frames = list(self.frames.values())
        self.frames.clear()

        # Xóa nút nav đang hoạt động
        self.active_nav = None
        # Gọi cleanup() và destroy() cho từng frame
        for frame in frames:
            try:
                cleanup = getattr(frame, "cleanup", None)
                if callable(cleanup):
                    cleanup()
            except Exception: # pylint: disable=broad-except
                logger.exception("Lỗi cleanup trang %s", type(frame).__name__)
            finally:
                try:
                    frame.destroy()
                except Exception: # pylint: disable=broad-except
                    logger.exception("Lỗi hủy trang %s", type(frame).__name__)

        # Cuối cùng cập nhật màu nút nav: không có nút nào được chọn
        self._update_nav_button_colors("")

    def get_information_from_server(self):
        """
        Lấy thông tin cập nhật phần mềm từ server trong một luồng riêng, tránh treo giao diện.
        """
        # Kiểm tra điều kiện: nếu đang đóng app, hoặc không có API_SERVER, hoặc APP_NAME không khớp với APP_NAME_SYSTEM thì bỏ qua
        if self._closing or not API_SERVER or APP_NAME != APP_NAME_SYSTEM:
            return

        # Nếu luồng kiểm tra cập nhật đang chạy, không tạo luồng mới
        if self._update_thread and self._update_thread.is_alive():
            return

        # API endpoint để kiểm tra phiên bản mới nhất
        endpoint = API_SERVER.rstrip("/") + "/update/" + APP_NAME_SYSTEM + "/latest-version"
        generation = self._login_generation

        # Tạo luồng riêng để gọi API và nhận thông tin cập nhật, tránh treo giao diện
        self._update_thread = threading.Thread(
            target=self.get_information_from_server_in_thread,
            args=(endpoint, generation), daemon=True, name="UpdateCheck")

        self._update_thread.start()

    def get_information_from_server_in_thread(self, endpoint, generation):
        """
        Worker chỉ gửi kết quả qua queue, không gọi Tk/after/messagebox.
        """
        try:
            with requests.get(endpoint, timeout=(5, 10)) as response:
                if response.status_code == 204:
                    return

                response.raise_for_status()
                info = response.json()
                if not isinstance(info, dict):
                    raise ValueError("Thông tin cập nhật không phải JSON object")

            if not self._stop_event.is_set():
                self._ui_queue.put(("update", (generation, info)))
        except Exception: # pylint: disable=broad-exception-caught
            logger.exception("Không thể kiểm tra cập nhật")

    def check_for_updates(self, version_info=None):
        """
        Kiểm tra và xử lý cập nhật phần mềm.
        """
        if self._closing or self.permission is None:
            return

        if version_info is None:
            try:
                version_info = self.data_update_queue.get_nowait()
            except queue.Empty:
                return

        try:
            newer = version.parse(version_info["latest_version"]) > version.parse(CURRENT_VERSION)
        except (KeyError, TypeError, version.InvalidVersion):
            logger.warning("Dữ liệu phiên bản không hợp lệ")
            return

        if newer and self.permission == version_info.get("update_for"):
            accepted = messagebox.askyesno("Cập nhật phần mềm",
                f"Đã có phiên bản {version_info['latest_version']}. Cập nhật ngay?", parent=self)

            if accepted:
                self.launch_updater()
            else:
                self.on_closing(force_close=True)

    def launch_updater(self):
        """
        Mở trình cập nhật phần mềm.
        """
        # APP_UPDATER có thể là đường dẫn tuyệt đối do bộ cài cung cấp.
        # Bản frozen thường dùng sys.executable; launcher tùy biến phải truyền
        # đường dẫn cài đặt thực tế, không dùng thư mục giải nén tạm.
        base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        updater = Path(APP_UPDATER)
        if not updater.is_absolute():
            updater = base / updater

        try:
            if not updater.is_file():
                raise FileNotFoundError(str(updater))

            # Updater phải chờ app hiện tại thoát trước khi thay file/mở app mới.
            subprocess.Popen([str(updater)], cwd=str(updater.parent))
        except OSError:
            logger.exception("Không thể mở updater")
            messagebox.showerror("Cập nhật", "Không thể mở updater. Ứng dụng tiếp tục hoạt động.", parent=self)
            return

        self.on_closing(force_close=True)

    def check_new_log(self):
        """
        Kiểm tra log trong 1 luồng riêng, nếu qua ngày mới thì chuyển tệp log sang thư mục tương ứng
        """
        if self._log_thread and self._log_thread.is_alive():
            return

        self._log_thread = threading.Thread(target=self.check_new_log_in_thread,
                                            daemon=True, name="LogRotation")
        self._log_thread.start()

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
            except Exception as e:   # pylint: disable=broad-except
                # Ghi log và dừng luồng
                logger.exception("Đã gặp lỗi trong luồng kiểm tra ghi nhật ký: %s. Dừng kiểm tra và thay đổi vị trí tệp log.", str(e))
                self.check_log_expire = False  # Dừng luồng khi gặp lỗi
                break  # Thoát khỏi vòng lặp

            # Mỗi 1 tiếng mới kiểm tra lại 1 lần
            if self._stop_event.wait(3600):
                break

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
        Hiển thị thông báo từ chối truy cập khi người dùng không có quyền truy cập vào chức năng.
        """
        messagebox.showwarning("Từ chối truy cập", "Bạn không có quyền truy cập vào chức năng này!", parent=self)

    def on_closing(self, force_close=False):
        """
        Đóng ứng dụng, hỏi xác nhận nếu không phải force_close.
        """
        if self._closing:
            return
        if not force_close and not messagebox.askokcancel(
                "Đóng ứng dụng", "Bạn có chắc chắn muốn thoát không?", parent=self):
            return
        self.destroy()

    def destroy(self):
        """
        Mọi đường thoát (kể cả callback cũ) đều dọn tài nguyên một lần.
        """
        if self._closing:
            return
        self._closing = True
        self._login_generation += 1
        self._login_pending = False
        self.permission = None
        self.current_auth = None
        self.current_session_token = None
        self.check_log_expire = False
        self._stop_event.set()

        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except TclError:
                pass
            self._poll_id = None
        self._clear_session_frames()
        self._destroy_login_window()
        self._stop_tray_icon()
        logger.info("Kết thúc chương trình %s", APP_NAME_SYSTEM)
        super().destroy()

    def _destroy_login_window(self):
        """
        Đóng cửa sổ đăng nhập nếu đang mở, và đặt self._login_window = None.
        """
        window, self._login_window = self._login_window, None
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except TclError:
                pass

    def open_window_login(self):
        """
        Mở cửa sổ đăng nhập nếu chưa có, hoặc đưa lên trước nếu đang mở.
        """
        if self._closing:
            return
        if self._login_pending:
            if self._login_window is not None:
                self._login_window.deiconify()
                self._login_window.lift()
            return

        self._login_generation += 1
        generation = self._login_generation
        self._login_pending = True

        # Callback chỉ đưa vào queue: an toàn cả khi LoginWindow gọi từ worker.
        try:
            self._login_window = LoginWindow(
                self,
                lambda permission: self._ui_queue.put(("login", (generation, permission))),
                lambda: self._ui_queue.put(("login_close", generation)),
                software_name=APP_NAME_SYSTEM,
                auto_login=self._allow_auto_login,
                session_store=self.session_store,
                auth_adapter=self.auth_adapter)
            # LoginWindow có thể đã khởi tạo store khi main chưa khởi tạo được.
            self.session_store = self._login_window.store
            self._allow_auto_login = False
        except Exception:
            self._login_pending = False
            raise

    def _poll_ui_queue(self):
        """
        Đọc các sự kiện từ self._ui_queue và xử lý chúng.
        """
        self._poll_id = None
        if self._closing:
            return

        for _ in range(100):
            try:
                action, payload = self._ui_queue.get_nowait()
            except queue.Empty:
                break

            try:
                if action == "login":
                    generation, permission = payload
                    if generation == self._login_generation and self._login_pending:
                        self.login_success(permission)
                elif action == "login_close":
                    if payload == self._login_generation and self._login_pending:
                        self.close_login_window()
                elif action == "restore":
                    self.restore_window()
                elif action == "hide":
                    self.hide_window()
                elif action == "quit":
                    self.on_closing(force_close=True)
                elif action == "update":
                    generation, info = payload
                    if generation == self._login_generation:
                        self.check_for_updates(info)
                elif action == "logout_revoke":
                    if not payload:
                        parent = self._login_window if self._login_window is not None else self
                        messagebox.showwarning("Đăng xuất",
                            "Đã xóa phiên trên máy này nhưng chưa xác nhận thu hồi phiên trên server. "
                            "Vui lòng kiểm tra kết nối hoặc liên hệ quản trị viên.", parent=parent)
                elif action == "tray_failed":
                    self.restore_window()
                    messagebox.showwarning("Khay hệ thống", "Không thể chạy biểu tượng khay. Cửa sổ được giữ mở.", parent=self)
            except Exception: # pylint: disable=broad-exception-caught
                logger.exception("Lỗi xử lý sự kiện UI: %s", action)

            if self._closing:
                return

        # Gọi lại hàm này sau 50ms
        self._poll_id = self.after(50, self._poll_ui_queue)

    def login_success(self, auth):
        """
        Sau khi đăng nhập:
        - Lưu quyền
        - Gọi kiểm tra cập nhật
        - Ẩn/hiện các nút nav theo quyền
        - Mặc định mở tab hợp lệ đầu tiên
        """
        if self._closing or not self._login_pending:
            return

        # Đánh dấu đăng nhập thành công và hủy cửa sổ đăng nhập
        self._login_pending = False
        self._destroy_login_window()

        # Không trả về thông tin phiên đăng nhập thì báo lỗi
        if not isinstance(auth, AuthSession):
            raise TypeError("LoginWindow phải trả AuthSession")

        self.current_auth = auth
        self.current_session_token = auth.token
        self.permission = auth.permission
        self.deiconify()
        # Tạo tray_icon cho phần mềm nếu đã login thành công
        self.create_tray_icon()
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
        Xử lý khi cửa sổ đăng nhập bị đóng mà chưa đăng nhập thành công.
        """
        self.on_closing(force_close=True)

    def on_quit(self):
        """
        Gọi khi người dùng chọn "Đóng chương trình" từ tray icon.
        """
        self._ui_queue.put(("quit", None))

    def hide_window(self):
        """
        Ẩn cửa sổ chính, nếu chưa có tray icon thì tạo tray icon trước.
        """
        if self._closing:
            return
        if self.permission is None:
            self.open_window_login()
            return
        # Không ẩn app khi chưa có icon để mở lại.
        if not self._tray_ready.is_set():
            self.create_tray_icon()
            return
        self.withdraw()

    def restore_window(self):
        """
        Khôi phục cửa sổ chính, nếu chưa có tray icon thì tạo tray icon trước.
        """
        if self._closing:
            return
        if self.permission is None:
            self.open_window_login()
            return
        self.deiconify()
        self.lift()

    def quit_app_from_tray_icon(self):
        """
        Gọi khi người dùng chọn "Đóng chương trình" từ tray icon.
        """
        self._ui_queue.put(("quit", None))

    def icon_thread(self, icon):
        """Dùng tham chiếu icon cố định; chỉ dành cho backend Windows."""
        def setup(ready_icon):
            with self._tray_lock:
                if not self._stop_event.is_set():
                    ready_icon.visible = True
                    self._tray_ready.set()
                    return
            # stop có thể được yêu cầu trước khi run sẵn sàng.
            ready_icon.stop()
        try:
            icon.run(setup=setup)
        except Exception: # pylint: disable=broad-except
            logger.exception("Tray icon gặp lỗi")
        finally:
            self._tray_ready.clear()
            if not self._stop_event.is_set():
                self._ui_queue.put(("tray_failed", None))

    def create_tray_icon(self):
        """Gọi nhiều lần vẫn chỉ có một icon/thread hoạt động."""
        if self._closing:
            return
        if self._tray_thread is not None and self._tray_thread.is_alive():
            return
        try:
            with Image.open(resource_path(IMAGE["ICO_IMG"])) as source:
                icon_image = source.copy()

            icon = pystray.Icon(
                "Quan", icon_image, APP_NAME_SYSTEM,
                menu=pystray.Menu(
                    MenuItem("Khôi phục", lambda icon, item: self._ui_queue.put(("restore", None)), default=True),
                    MenuItem("Ẩn", lambda icon, item: self._ui_queue.put(("hide", None))),
                    MenuItem("Đóng chương trình", lambda icon, item: self._ui_queue.put(("quit", None)))))
            self.tray_icon = icon

            # Luồng tạo icon tray
            self._tray_thread = threading.Thread(target=self.icon_thread,
                args=(icon,), daemon=True, name="SystemTray")
            self._tray_thread.start()

        except Exception: # pylint: disable=broad-except
            logger.exception("Không tạo được tray icon")
            self.tray_icon = None
            self._ui_queue.put(("tray_failed", None))

    def _stop_tray_icon(self):
        """
        Dừng tray icon và thread liên quan.
        """
        with self._tray_lock:
            icon = self.tray_icon
            ready = self._tray_ready.is_set()
        if icon is not None and ready:
            try:
                icon.stop()
            except Exception: # pylint: disable=broad-except
                logger.exception("Không dừng được tray icon")

        # Nếu chưa ready, setup() sẽ nhận stop_event và tự dừng.
        thread = self._tray_thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
            if thread.is_alive():
                logger.warning("Tray thread chưa kết thúc trong 2 giây")
        self._tray_ready.clear()
        self.tray_icon = None

def run_app():
    """
    Kiểm tra xem ứng dụng đã chạy chưa, nếu đã chạy thì không mở lại.
    Nếu chưa chạy thì mở ứng dụng.
    """
    # Giữ tên này cố định giữa các lần mở ứng dụng. Nó giống như ID, nếu mở 1 ID 2 lần là bị chặn
    mutex_name = r"Local\Quan.SingleInstance"
    try:
        with single_instance(mutex_name):
            app = App()
            try:
                app.mainloop()
            finally:
                app.destroy()
    except AlreadyRunningError as exc:
        print(exc)
        return 0

# Ví dụ chạy thử:
if __name__ == "__main__":
    multiprocessing.freeze_support()
    # Tắt hỗ trợ HIGH DPI của customtkinter, tuy nhiên nếu kích thước màn hình lớn hơn 100% khiến giao diện bị mờ
    # chức năng này tự động bật, và có thể làm co giãn kích thước theo độ phân giải màn hình, cũng gây ra lỗi chữ bé hơn trong các treeview được đặt vào frame
    # ctk.deactivate_automatic_dpi_awareness()
    # Kiểm tra xem ứng dụng đã chạy chưa, nếu đã chạy thì không mở lại
    run_app()
    # Khởi động phần mềm mà không cần kiểm tra lại
    # app = App()
