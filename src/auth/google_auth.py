import threading
import os
import requests         # Gọi API userinfo của Google
from google_auth_oauthlib.flow import InstalledAppFlow  # Flow OAuth2 cho app desktop

class GoogleAuthService:
    """
    Dịch vụ login Google cho desktop app.
    """

    def __init__(self, client_secret_file: str, scopes: list[str]):
        """
        client_secret_file: đường dẫn google_client_secret.json
        scopes: danh sách scope OIDC
        """
        self.client_secret_file = client_secret_file
        self.scopes = scopes

    def start_login(
        self,
        on_success,
        on_error,
        timeout_seconds: int = 30,
        host: str = "localhost",
        port: int = 8765
    ):
        """
        Bắt đầu login Google ở background thread.

        on_success: callback nhận user_info dict
        on_error: callback nhận Exception
        timeout_seconds: thời gian chờ tối đa để tránh treo popup
        """
        # Chạy logic OAuth ở luồng nền để UI không bị đơ
        t = threading.Thread(
            target=self._oauth_worker,
            args=(on_success, on_error, timeout_seconds, host, port),
            daemon=True
        )
        t.start()

    def _oauth_worker(self, on_success, on_error, timeout_seconds, host, port):
        """
        Luồng thực thi xác thực đăng nhập bằng Google
        """
        try:
            # Kiểm tra xem tồn tại tệp cấu hình đăng nhập không
            if not os.path.exists(self.client_secret_file):
                raise FileNotFoundError(
                    f"Không tìm thấy tệp cấu hình đăng nhập bằng google: {self.client_secret_file}"
                )
            
            # Tạo OAuth flow từ thư viện được cung cấp bởi GG
            flow = InstalledAppFlow.from_client_secrets_file(
                self.client_secret_file,
                scopes=self.scopes
            )

            # Container để lấy creds từ thread con
            result_container = {"creds": None, "error": None}

            # Hàm chạy local server OAuth
            def _run_local():
                try:
                    creds = flow.run_local_server(
                        host=host,
                        port=port,
                        open_browser=True
                    )
                    result_container["creds"] = creds
                except Exception as e:
                    result_container["error"] = e

            # Chạy run_local_server trong thread con
            inner = threading.Thread(target=_run_local, daemon=True)
            inner.start()

            # Chờ tối đa timeout_seconds
            inner.join(timeout_seconds)

            # Nếu user đóng tab/không login → timeout
            if inner.is_alive():
                try:
                    # "Đánh thức" local server để thoát chờ
                    requests.get(f"http://{host}:{port}/", timeout=1.5)
                except Exception:
                    pass

                inner.join(3)
                raise TimeoutError("Đăng nhập Google đã bị hủy hoặc quá thời gian.")

            # Nếu thread con báo lỗi
            if result_container["error"]:
                raise result_container["error"]

            # Lấy credentials
            creds = result_container["creds"]
            if not creds:
                raise Exception("Không nhận được credentials từ Google.")

            # Gọi userinfo endpoint
            resp = requests.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=10
            )
            resp.raise_for_status()

            # Parse JSON user_info
            user_info = resp.json()

            # Trả kết quả về UI qua callback
            on_success(user_info)

        except Exception as e:
            # Trả lỗi về UI qua callback
            on_error(e)
