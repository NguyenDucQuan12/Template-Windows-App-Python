# auth/facebook_auth.py

import threading
import secrets
import string
import webbrowser
import urllib.parse
import http.server
import socketserver
import requests

class FacebookAuthService:
    """
    Dịch vụ login Facebook cho desktop app.
    """

    def __init__(self, app_id: str, app_secret: str, redirect_uri: str, scopes: list[str], redirect_port: int, redirect_path: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.redirect_uri = redirect_uri
        self.scopes = scopes
        self.redirect_port = redirect_port
        self.redirect_path = redirect_path

    def start_login(self, on_success, on_error, timeout_seconds: int = 30):
        """
        Bắt đầu login Facebook ở background thread.
        """
        t = threading.Thread(
            target=self._oauth_worker,
            args=(on_success, on_error, timeout_seconds),
            daemon=True
        )
        t.start()

    def _oauth_worker(self, on_success, on_error, timeout_seconds):
        """
        Worker chạy OAuth Facebook.
        """
        auth_result = {"code": None, "state": None, "error": None}

        # Sinh state chống CSRF
        state = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))

        # Handler nhận callback
        class FacebookOAuthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                try:
                    parsed = urllib.parse.urlparse(self.path)
                    path = parsed.path
                    query = urllib.parse.parse_qs(parsed.query)

                    if path == self.server.redirect_path:
                        code_list = query.get("code")
                        state_list = query.get("state")
                        error_list = query.get("error")

                        if error_list:
                            auth_result["error"] = error_list[0]
                        elif not code_list or not state_list:
                            auth_result["error"] = "missing_code_or_state"
                        else:
                            code = code_list[0]
                            state_returned = state_list[0]

                            if state_returned != state:
                                auth_result["error"] = "invalid_state"
                            else:
                                auth_result["code"] = code
                                auth_result["state"] = state_returned

                        self.send_response(200)
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                        self.end_headers()
                        self.wfile.write(
                            b"<html><body><h3>Dang nhap Facebook thanh cong. Ban co the dong tab nay.</h3></body></html>"
                        )
                    else:
                        self.send_response(404)
                        self.end_headers()

                except Exception as e:
                    auth_result["error"] = str(e)
                    self.send_response(500)
                    self.end_headers()

            # Tắt log console
            def log_message(self, format, *args):
                return

        try:
            # Tạo local server
            with socketserver.TCPServer(("localhost", self.redirect_port), FacebookOAuthHandler) as httpd:
                httpd.allow_reuse_address = True
                httpd.timeout = 1.0

                # Gắn data vào server object để handler truy cập
                httpd.redirect_path = self.redirect_path

                # Tạo URL authorize
                params = {
                    "client_id": self.app_id,
                    "redirect_uri": self.redirect_uri,
                    "state": state,
                    "scope": ",".join(self.scopes),
                    "response_type": "code"
                }

                auth_url = "https://www.facebook.com/v20.0/dialog/oauth?" + urllib.parse.urlencode(params)

                # Mở browser
                webbrowser.open(auth_url)

                # Polling không treo
                elapsed = 0
                while elapsed < timeout_seconds and auth_result["code"] is None and auth_result["error"] is None:
                    httpd.handle_request()
                    elapsed += httpd.timeout

                if auth_result["error"]:
                    raise Exception(f"Facebook OAuth error: {auth_result['error']}")

                if auth_result["code"] is None:
                    raise TimeoutError("Đăng nhập Facebook đã bị hủy hoặc quá thời gian.")

            # Đổi code -> access_token
            token_params = {
                "client_id": self.app_id,
                "redirect_uri": self.redirect_uri,
                "client_secret": self.app_secret,
                "code": auth_result["code"]
            }

            token_resp = requests.get(
                "https://graph.facebook.com/v20.0/oauth/access_token",
                params=token_params,
                timeout=10
            )
            token_resp.raise_for_status()

            access_token = token_resp.json().get("access_token")
            if not access_token:
                raise Exception("Không nhận được access_token từ Facebook.")

            # Lấy user info
            user_resp = requests.get(
                "https://graph.facebook.com/me",
                params={"fields": "id,name,email", "access_token": access_token},
                timeout=10
            )
            user_resp.raise_for_status()

            user_info = user_resp.json()

            # Trả user_info về UI
            on_success(user_info)

        except Exception as e:
            on_error(e)
