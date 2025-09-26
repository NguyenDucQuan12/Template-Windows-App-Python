"""
ModalLoadingPopup: Popup loading dùng chung cho mọi frame/CTkFrame.
- Căn giữa trên frame cha (theo tọa độ thực) và tự "đu" theo khi cha di chuyển/resize.
- Khóa toàn bộ cửa sổ chính (wm_attributes -disabled True) + grab_set để ngăn tương tác.
- An toàn luồng UI (chỉ thao tác Tk trên main thread; nếu không, dùng .after(0,...)).
- Chống gọi trùng (re-entrant): nhiều lệnh show() liên tiếp không sinh thêm cửa sổ.
- Thu gom tài nguyên GIF và phục hồi trạng thái cửa sổ an toàn kể cả khi lỗi.
- Có thể dùng như context manager: with ModalLoadingPopup(parent): ... -> auto show/hide.
"""

import customtkinter
from tkinter import TclError
import threading
import logging
from typing import Optional, Tuple

from utils.loading_gif import LoadingGifLabel
from utils.resource import resource_path

logger = logging.getLogger(__name__)


class ModalLoadingPopup:
    """
    Quản lý vòng đời popup loading dạng modal.
    Dùng được cho bất cứ CTkFrame/CTk/Toplevel nào làm 'parent'.
    """

    def __init__( self, parent: customtkinter.CTk | customtkinter.CTkFrame, *, size: Tuple[int, int] = (150, 150), gif_path: Optional[str] = None,
        gif_size: Tuple[int, int] = (150, 150), text: str = "", fg_color: Tuple[str, str] | str = ("#3cb371", "#3cb371"), topmost: bool = True,
        block_main_window: bool = True,
    ):
        """
        Parameters
        ----------
        parent : CTk | CTkFrame
            Widget cha. Popup sẽ căn giữa tương đối theo widget này.
        size : (w, h)
            Kích thước cửa sổ popup.
        gif_path : str | None
            Đường dẫn GIF. Nếu None -> mặc định assets/images/loading/loading_gif.gif.
        gif_size : (w, h)
            Kích thước hiển thị GIF.
        text : str
            Dòng chữ phụ (nếu cần).
        fg_color : tuple|str
            Màu nền popup (CTkToplevel).
        topmost : bool
            Đưa popup lên trên cùng.
        block_main_window : bool
            Nếu True, vô hiệu hóa toàn bộ cửa sổ gốc (Windows hỗ trợ tốt).
        """
        self.parent = parent
        self.size = size
        self.gif_path = gif_path or resource_path(r"assets\images\loading\loading_gif.gif")
        self.gif_size = gif_size
        self.text = text  # Văn bản hiển thị ở giữa
        self.fg_color = fg_color
        self.topmost = topmost
        self.block_main_window = block_main_window

        self._popup: Optional[customtkinter.CTkToplevel] = None
        self._gif_label: Optional[LoadingGifLabel] = None
        self._is_showing = False
        self._disabled_set = False
        self._bound = False  # đã bind sự kiện theo dõi parent hay chưa

    # ----------------------------- Public API -----------------------------

    def show(self):
        """
        Hiển thị popup (idempotent).  
        Chỉ sử dụng hàm này khi đang ở luồng chính (Không nằm trong thread vì tkinter chỉ cho phép thay đổi giao diện chương trình tại Main Thread)
        """
        # Kiểm tra chương trình có đang chạy trên thread
        if not self._on_ui_thread():
            # Nếu đang chạy trên thread thì sử dụng cú pháp self.after để khởi động an toàn
            try:
                self._root().after(0, self.show)
            except Exception as e:
                logger.error("Không thể hiển thị popup loading về main thread: %s", e)
            return

        # Kiểm tra nếu popup đã đươc hiển thị thì ko mở thêm 1 popup nữa
        if self._is_showing:
            return

        # Tiến hành mở popup
        try:
            self._ensure_popup()
            self._place_center()
            self._apply_modal_state()
            self._bind_parent_changes()
            self._is_showing = True
        except TclError as te:
            logger.error("Lỗi Tcl khi show popup: %s", te)
            self._is_showing = False
            self._safe_destroy()

    def hide(self):
        """
        Ẩn popup và phục hồi cửa sổ chính (mở khóa). Idempotent.
        """
        # Kiểm tra xem có đang chạy popup trên 1 luồng riêng không
        if not self._on_ui_thread():
            # Nếu chạy trong luồng thì sử dụng cú pháp self.after để đảm bảo không gây xung đột
            try:
                self._root().after(0, self.hide)
            except Exception as e:
                logger.error("Không thể tắt popup loading trong luông về main thread: %s", e)
            return
        # Nếu không có popup nào đang chạy thì bỏ qua
        if not self._is_showing:
            return

        # Giải phóng cửa sổ chính để thao tác và thu gom các rác thải khi sử dụng gif
        try:
            # Không unbind do hạn chế của customtkinter; callback sẽ no-op khi _is_showing=False
            self._release_modal_state()
            self._safe_destroy()
            self._is_showing = False
        # Nếu xảy ra lỗi thì sử dụng cách mở khóa ép buộc
        except TclError as te:
            logger.error("Lỗi Tcl khi hide popup: %s", te)
            # Dù lỗi cũng cố mở khóa
            self._release_modal_state(force=True)
            self._is_showing = False

    def schedule_show(self):
        """
        Gọi show() an toàn từ mọi thread.  
        Sử dụng khi đang ở trong 1 thread
        """
        try:
            self._root().after(0, self.show)
        except Exception as e:
            logger.exception("Không thể schedule_show(): %s", e)

    def schedule_hide(self):
        """
        Gọi hide() an toàn từ mọi thread.  
        Sử dụng khi đang ở trong thread
        """
        try:
            self._root().after(0, self.hide)
        except Exception as e:
            logger.exception("Không thể schedule_hide(): %s", e)

    # ------------------------ Context manager API -------------------------
    # Chỉ sử dụng trong các tác vụ ngắn, không làm đóng băng UI
    def __enter__(self):
        """
        Ví dụ sử dụng như sau:  
        ```python
        popup = ModalLoadingPopup(parent)
        with popup:
            # công việc ngắn: cập nhật UI / gọi hàm nhanh
            do_quick_task()
        ```
        Hàm with sẽ tự động gọi hàm exit khi kết thúc
        """
        self.show()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.hide()
        return False  # không nuốt exception bên trong with

    # ---------------------------- Internals -------------------------------

    def _root(self) -> customtkinter.CTk:
        """Lấy CTk root từ parent."""
        return self.parent.winfo_toplevel()  # type: ignore

    def _on_ui_thread(self) -> bool:
        """
        Kiểm tra xem chương trình có đang chạy trên thread hay không
        """
        return threading.current_thread() is threading.main_thread()

    def _ensure_popup(self):
        """Khởi tạo cửa sổ popup + nạp GIF (mỗi lần show tạo một popup mới)."""
        # Cập nhật thông tin về cửa sổ cha tại thời điểm mới nhất để lấy vị trí, kích thước, ...
        try:
            self.parent.update_idletasks()
        except TclError:
            # Nếu parent đã bị destroy, fallback về root
            self.parent = self._root()
            self.parent.update_idletasks()

        # Tạo Toplevel để hiển thị popup lên trên cùng
        self._popup = customtkinter.CTkToplevel(self.parent, fg_color=self.fg_color)
        # Tạm thời ẩn cho đến khi cấu hình xong
        self._popup.withdraw()
        # Loại bỏ title của cửa sổ (ẩn nút thu nhỏ, phóng to, ...)
        self._popup.overrideredirect(True)

        # Đặt cửa sổ là transient để gắn với toplevel gốc (tốt cho focus ở một số nền tảng)
        try:
            self._popup.transient(self._root())
        except TclError:
            pass
        
        # Đặt cửa sổ này là trên cùng, nếu lỗi thì bỏ qua
        if self.topmost:
            try:
                self._popup.attributes("-topmost", True)
            except TclError:
                pass

        # Kích thước
        w, h = self.size
        try:
            self._popup.geometry(f"{w}x{h}+0+0")
        except TclError:
            pass

        # Nội dung popup
        self._gif_label = LoadingGifLabel(self._popup, resize=self.gif_size, text=self.text)
        self._gif_label.pack(fill="both", expand=True, padx=4, pady=4)

        # Nạp GIF, nếu lỗi thì thay bằng text
        try:
            self._gif_label.load(self.gif_path)
        except Exception as e:
            logger.exception("Không thể nạp GIF '%s': %s", self.gif_path, e)
            self._gif_label.configure(text="Đang xử lý...", image=None)

        # Hiện lên
        try:
            self._popup.deiconify()
            self._popup.update_idletasks()
        except TclError:
            pass

    def _apply_modal_state(self):
        """Khóa tương tác cửa sổ chính + grab."""
        if self.block_main_window:
            try:
                # Vô hiệu hóa cửa sổ gốc
                self._root().wm_attributes("-disabled", True)
                self._disabled_set = True  # Đặt flag để xác nhận
            except TclError:
                self._disabled_set = False

        # Khóa focus/chuột/phím vào cửa sổ popup
        try:
            self._popup.grab_set()
        except TclError:
            pass
        
        # Chuyển focus vào popup
        try:
            self._popup.focus_set()
        except TclError:
            pass

    def _release_modal_state(self, force: bool = False):
        """Mở khóa cửa sổ chính + nhả grab."""
        try:
            # Nhả grap, không còn chặn sự kiện nữa
            if self._popup is not None:
                self._popup.grab_release()
        except TclError:
            pass

        # Nếu đã khóa thao tác với cửa sổ chính thì giải phóng
        if self._disabled_set or force:
            try:
                self._root().wm_attributes("-disabled", False)
            except TclError:
                pass

        # Reset lại trạng thái
        self._disabled_set = False

    def _safe_destroy(self):
        """Hủy popup + thu gom tài nguyên GIF an toàn."""
        try:
            if self._gif_label is not None:
                try:
                    if hasattr(self._gif_label, "unload"):
                        self._gif_label.unload()
                except Exception as e:
                    logger.debug("Lỗi unload GIF (bỏ qua): %s", e)
                self._gif_label = None

            if self._popup is not None:
                try:
                    self._popup.destroy()
                except TclError:
                    pass
                self._popup = None
        except Exception as e:
            logger.debug("Lỗi _safe_destroy (bỏ qua): %s", e)

    # ----------------------- Centering & Reposition -----------------------

    def _parent_screen_rect(self) -> Tuple[int, int, int, int]:
        """
        Trả về (x, y, w, h) tuyệt đối của parent trên màn hình.
        Dùng để căn giữa popup.
        """
        # Lấy tọa độ vị trí và kích thước của frame cha
        try:
            self.parent.update_idletasks()
            x = self.parent.winfo_rootx()
            y = self.parent.winfo_rooty()
            w = self.parent.winfo_width()
            h = self.parent.winfo_height()
            return x, y, max(w, 1), max(h, 1)
        except TclError:
            # Fallback: root
            root = self._root()
            root.update_idletasks()
            return (
                root.winfo_rootx(),
                root.winfo_rooty(),
                max(root.winfo_width(), 1),
                max(root.winfo_height(), 1),
            )

    def _place_center(self):
        """Đặt popup vào giữa parent."""
        if self._popup is None:
            return
        # Lấy vị trí và kích thước của cửa sổ cha
        px, py, pw, ph = self._parent_screen_rect()
        w, h = self.size
        # Tính toán vị trí trung tâm của cửa sổ cha
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2

        # ĐẶt popup vào vị trí chính giữa
        try:
            self._popup.geometry(f"{w}x{h}+{x}+{y}")
        except TclError:
            pass

    def _bind_parent_changes(self):
        """
        Bind theo dõi parent để popup luôn giữ trung tâm khi di chuyển/resize.
        KHÔNG unbind do hạn chế của customtkinter; chỉ bind đúng 1 lần.
        """
        # Nếu đã có sự kiện bind thì bỏ qua, ko lặp lại tránh memory leak
        if self._bound:
            return
        # chỉ bind một lần cho vòng đời đối tượng
        # Add = + để ko ghi đè các sự kiện hệ thống, chỉ thêm mới các sự kiện này
        try:
            # Kích hoạt khi cửa sổ cha thay đổi kích thước, vị trí
            self.parent.bind("<Configure>", self._on_parent_configure, add="+")
            # Thay đổi khi widget được map hiện lại lên màn hình
            self.parent.bind("<Map>", self._on_parent_configure, add="+")
            self._bound = True
        except TclError:
            self._bound = False

    def _on_parent_configure(self, _event=None):
        """
        Callback khi parent thay đổi kích thước/vị trí.
        Chỉ chạy khi popup đang hiển thị.
        """
        if self._is_showing and self._popup is not None:
            self._place_center()
