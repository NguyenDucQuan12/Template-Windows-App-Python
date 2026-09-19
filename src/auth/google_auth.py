"""
Dịch vụ OAuth Google trong một worker thread.
"""
import logging
import threading
from pathlib import Path

import requests
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)
class GoogleAuthError(RuntimeError):
    """Thông báo đã làm sạch, có thể hiển thị trên giao diện."""


class _DesktopGoogleFlow(InstalledAppFlow):
    """
    Giới hạn thời gian gọi endpoint đổi authorization code lấy token.

    timeout_seconds của run_local_server chỉ giới hạn thời gian chờ
    trình duyệt trả kết quả, không phải toàn bộ quá trình OAuth.
    """

    def fetch_token(self, **kwargs):
        # timeout = (thời gian kết nối, thời gian chờ đọc dữ liệu).
        kwargs.setdefault("timeout", (5, 15))
        return super().fetch_token(**kwargs)


class GoogleAuthService:
    """
    Thực hiện OAuth Google trong một worker thread.
    """

    def __init__(self, client_secret_file: str, scopes: list[str]):
        """
        Thực hiện kết nối tới dịch vụ google
        """
        self.client_secret_file = Path(client_secret_file)
        self.scopes = list(scopes)

        # Một instance service chỉ thực hiện một lần OAuth tại một thời điểm.
        self._login_lock = threading.Lock()

    def start_login(self, on_success, on_error, timeout_seconds: int = 120, host: str = "127.0.0.1", port: int = 0) -> bool:
        """
        Tiến hành đăng nhập bằng dịch vụ google  
        Trả True: đã bắt đầu.  
        Trả False: service đang có một lần OAuth khác.
        """
        if host not in {"127.0.0.1", "localhost"}:
            raise ValueError("OAuth desktop chỉ được lắng nghe trên loopback.")

        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds phải lớn hơn 0.")

        # Kiểm tra lock trước khi tạo thread để tránh tạo nhiều thread cùng lúc.
        try:
            if not self._login_lock.acquire(blocking=False):
                return False
        except Exception: # pylint: disable=broad-except
            return False

        # Tạo thread để thực hiện OAuth Google trên trinh duyệt. Nếu thread ném exception, lock sẽ được giải phóng trong finally của _oauth_worker.
        # Thời gian cho việc người dùng xác thực là 120s
        worker = threading.Thread(
            target=self._oauth_worker,
            args=(on_success, on_error, timeout_seconds, host, port),
            daemon=True)

        try:
            worker.start()
        except Exception as e: # pylint: disable=broad-except
            logger.exception("Không thể bắt đầu thread OAuth Google: %s", str(e))
            self._login_lock.release()
            raise

        return True

    def _oauth_worker(self, on_success, on_error, timeout_seconds, host, port):
        """
        Chạy trong một thread riêng để thực hiện OAuth Google.
        """
        flow = None
        user_info = None
        error = None

        try:
            if not self.client_secret_file.is_file():
                raise GoogleAuthError("Không tìm thấy cấu hình đăng nhập Google.")

            # OAuth Google chỉ được thực hiện trong một thread tại một thời điểm.
            # from_client_secrets_file() sẽ đọc file JSON và tạo một session HTTP để gọi endpoint Google. Nếu nhiều thread cùng gọi, session sẽ bị xung đột.
            flow = _DesktopGoogleFlow.from_client_secrets_file(
                str(self.client_secret_file),
                scopes=self.scopes,
                autogenerate_code_verifier=True,
            )

            # File cấu hình phải được tạo cho ứng dụng Desktop.
            if flow.client_type != "installed":
                raise GoogleAuthError("Cấu hình Google phải thuộc loại Desktop app.")

            # Tạo một server HTTP tạm thời để nhận callback từ Google.
            credentials = flow.run_local_server(
                host=host,
                port=port,
                open_browser=True,
                timeout_seconds=timeout_seconds,
                prompt="select_account",
                access_type="online",
                authorization_prompt_message=None,
                success_message=(
                    "Da nhan phan hoi Google. "
                    "Hay quay lai ung dung de hoan tat."
                ),
            )

            # Access token chỉ sử dụng trong bộ nhớ để lấy danh tính Google.
            with requests.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {credentials.token}"}, timeout=(5, 15)) as response:
                response.raise_for_status()
                user_info = response.json()

            if not isinstance(user_info, dict):
                raise GoogleAuthError("Google trả thông tin tài khoản không hợp lệ.")

            google_sub = user_info.get("sub")

            if not isinstance(google_sub, str) or not google_sub.strip():
                raise GoogleAuthError("Không nhận được định danh tài khoản Google.")

        except GoogleAuthError as exc:
            error = exc

        except Exception: # pylint: disable=broad-except
            # Không đưa nguyên exception OAuth/HTTP lên UI:
            # có thể chứa URL callback hoặc thông tin nhạy cảm.
            error = GoogleAuthError("Không hoàn tất xác thực Google.Bạn có thể đã hủy, quá thời gian chờ hoặc kết nối mạng gặp lỗi. Vui lòng thử lại.")

        finally:
            # Tiến hành giải phóng lock trong finally để tránh deadlock nếu on_success/on_error ném exception.
            try:
                if flow is not None:
                    flow.oauth2session.close()
            finally:
                self._login_lock.release()

        # Đặt callback ngoài try của OAuth: lỗi trong callback không bị hiểu nhầm là lỗi xác thực.
        if error is not None:
            on_error(error)
        else:
            on_success(user_info)
