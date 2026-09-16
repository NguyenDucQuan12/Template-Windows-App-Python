"""
Bảo vệ remember-token bằng Windows DPAPI (CurrentUser); không lưu password.
Định danh/path cố định, độc lập với vị trí exe hoặc thư mục giải nén.
"""
from __future__ import annotations
import ctypes
from datetime import datetime
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import threading

class StoreError(RuntimeError):
    """
    Lỗi
    """

class DPAPIProtector:
    """
    Lớp mã hóa và giải mã session của Window
    """
    ENTROPY = b"Quan.RememberLogin.v1"  # Domain separation; KHÔNG phải khóa bí mật.

    def _transform(self, data: bytes, decrypt: bool) -> bytes:
        """
        Hàm chung cho giải mã và mã hóa
        """
        # TRánh chạy DPAPI trên hệ điều hành khác
        if os.name != "nt":
            raise StoreError("DPAPI chỉ hỗ trợ Windows")
        
        class Blob(ctypes.Structure):
            """
            Class mô tả vùng dữ liệu cho Window 
            """
            _fields_ = [("cbData", wintypes.DWORD),                         # số byte
                        ("pbData", ctypes.POINTER(ctypes.c_ubyte))]         # Địa chỉ vùng nhớ chứa các byte

        # Nạp DLL của windows
        crypt = ctypes.WinDLL("crypt32", use_last_error=True)       # chứa các hàm DPAPI. use_last_error=True: cho phép lấy mã lỗi Windows của lời gọi.
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)     # cung cấp LocalFree. use_last_error=True: cho phép lấy mã lỗi Windows của lời gọi.

        # Lấy hàm mã hóa và khai báo 7 kiểu tham số
        protect = crypt.CryptProtectData
        protect.argtypes = [ctypes.POINTER(Blob),       # con trỏ tới dữ liệu đầu vào
                            wintypes.LPCWSTR,           # Chuỗi mô tả Unicode
                            ctypes.POINTER(Blob),       # Con trỏ tới entropy
                            ctypes.c_void_p,            # Tham số dự phòng
                            ctypes.c_void_p,            # Cấu hình hộp thoại
                            wintypes.DWORD,             # Cờ tùy chọn
                            ctypes.POINTER(Blob)]       # Con trỏ tới cấu trúc nhận kết quả

        # Kết quả trả về cho biết thành công/thất bại. Dữ liệu mã hóa được ghi qua tham số thứ bảy.
        protect.restype = wintypes.BOOL

        # Lấy hàm giải mã
        unprotect = crypt.CryptUnprotectData
        unprotect.argtypes = [ctypes.POINTER(Blob),
                              ctypes.c_void_p,          # Nơi nhận mô tả
                              ctypes.POINTER(Blob),
                              ctypes.c_void_p,
                              ctypes.c_void_p,
                              wintypes.DWORD,
                              ctypes.POINTER(Blob)]

        # Khai báo kết quả thành công hay thất bại
        unprotect.restype = wintypes.BOOL

        # Khai báo hàm giải phóng vùng nhớ Windows cấp cho kết quả. Các khai báo kiểu này giúp tránh truyền sai kích thước/con trỏ, đặc biệt với Python 64-bit
        free = kernel.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p

        # Tạo vùng nhớ chứa dữ liệu để hàm Windows đọc
        buf = ctypes.create_string_buffer(data)
        # Tạo vùng nhớ chứa entropy
        entropy_buf = ctypes.create_string_buffer(self.ENTROPY)

        # Tạo cấu trúc mô tả đầu vào, lấy số byte thực và biểu diễn địa chỉ buffer dưới dạng con trỏ byte
        incoming = Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        # Tương tự với entropy
        entropy = Blob(len(self.ENTROPY), ctypes.cast(entropy_buf, ctypes.POINTER(ctypes.c_ubyte)))
        # Tạo 1 cấu trúc rỗng để Window ghi địa chỉ và kích thước kết quả
        outgoing = Blob()

        # Chọn giải mã hay mã hóa
        fn = unprotect if decrypt else protect
        # Mô tả khi mã hóa, còn giải mã thì không cần mô tả
        description = None if decrypt else "Quan remembered session"

        if not fn(
            ctypes.byref(incoming),         # địa chỉ cấu trúc để Windows đọc/ghi.
            description,
            ctypes.byref(entropy),
            None,                           # Không dùng tham số dự phòng
            None,                           # Không dùng hộp thoại
            0x1,                            # cờ CRYPTPROTECT_UI_FORBIDDEN.
            ctypes.byref(outgoing)          # nhận kết quả.
        ):  # UI_FORBIDDEN
            # Nếu lỗi thì lấy lỗi và thông báo
            code = ctypes.get_last_error()
            raise StoreError(f"Windows không thể bảo vệ/đọc phiên (mã {code})")

        # Nếu thành công thì sao chép kết quả từ vùng nhớ Window sang 1 đối tượng bytwa của Python
        try:
            return ctypes.string_at(outgoing.pbData, outgoing.cbData)
        finally:
            # Trước khi return thì chạy finally
            # Nếu có vùng nhớ đầu ra thì ghi số 0 lên vùng đó và giải phóng bộ nhớ
            # Windows yêu cầu giải phóng đầu ra DPAPI bằng LocalFree
            if outgoing.pbData:
                ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
                free(outgoing.pbData)

    def protect(self, data: bytes) -> bytes:
        """
        Mã hóa session
        """
        return self._transform(data, False)

    def unprotect(self, data: bytes) -> bytes:
        """
        Giải mã session
        """
        return self._transform(data, True)

def atomic_write(path: Path, data: bytes) -> None:
    """
    Ghi file tạm và sau đó ghi đè lên file gốc  
    Tránh viết dở trực tiếp lên file phiên đang dùng
    """
    # Tạo thư mục tạm
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None

    try:
        # Tạo file tạm trùng tên nhưng có đuôi là .tmp
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            # Đẩy dữ liệu khỏi bộ đệm python xuống hệ điều hành
            stream.flush()
            # đồng bộ dữ liệu của file qua hệ điều hành
            os.fsync(stream.fileno())

        # Sau khi file tạm hoàn thành thì thay thế file chính bằng file này
        os.replace(temporary, path)
    finally:
        # Dọn file tạm nếu vẫn tồn tại. Nếu đã được chuyển thành file đích thì không báo lỗi.
        if temporary is not None:
            temporary.unlink(missing_ok=True)

class SessionStore:
    """
    Session Store
    """
    # Dấu nhận diện định dạng file. Phần này được lưu công khai ở đầu file
    MAGIC = b"QUAN-DPAPI-1\n"
    # Giới hạn file phiên 65.536 byte, tức 64 KiB.
    MAX_BYTES = 65536

    def __init__(self, path=None, protector=None):
        if path is None:
            # Nếu không chỉ định đường dẫn cụ thể thì sử dụng thu mục local trên window của user hiện tại
            local = os.environ.get("LOCALAPPDATA")
            if not local or not Path(local).is_absolute():
                raise StoreError("Không xác định được LOCALAPPDATA")

            # Tạo đường dẫn hoàn chỉnh như sau: C://User/Tên máy tính/AppData/Local/Quan/Auth/remembered-session.bin
            path = Path(local) / "Quan" / "Auth" / "remembered-session.bin"

        self.path = Path(path)
        # Bộ mã hóa truyền vào hoặc dùng DPAPIProtector
        self.protector = protector or DPAPIProtector()
        # Tạo khóa có thể được cùng một thread lấy lại nhiều lần.
        self._lock = threading.RLock()

    @staticmethod
    def _validate(record):
        """
        Xác thực dữ liệu trước khi lưu và sau khi đọc
        """
        # Yêu cầu dictionary và phiên bản 1.
        if not isinstance(record, dict) or record.get("version") != 1:
            raise StoreError("Phiên đã lưu sai định dạng")

        # Danh sách các trường được phép lưu
        required = {"version", "email", "provider", "session_token", "expires_at"}
        # Thiếu trường hoặc thêm trường đều bị từ chối.
        if set(record) != required:
            raise StoreError("Phiên chứa trường không hợp lệ")
        
        for field in ("email", "provider", "session_token", "expires_at"):
            # Validation các trường, không rỗng và không quá dài
            if not isinstance(record[field], str) or not record[field] or len(record[field]) > 8192:
                raise StoreError("Phiên chứa giá trị không hợp lệ")

        # Chỉ chấp nhận 3 provider tương ứng với 3 cách đăng nhập
        if record["provider"] not in {"local", "google", "facebook"}:
            raise StoreError("Provider không hợp lệ")
        
        # Phân tích thời hạn
        try:
            expiry = datetime.fromisoformat(record["expires_at"])
        except ValueError as exc:
            raise StoreError("Hạn phiên không hợp lệ") from exc

        if expiry.tzinfo is None:
            raise StoreError("Hạn phiên phải có múi giờ")

        return record

    def load(self):
        """
        Đọc, giải mã và kiểm tra
        """
        # Giữ khóa
        with self._lock:
            try:
                # Mở file nhị phân để đọc
                with self.path.open("rb") as stream:
                    blob = stream.read(self.MAX_BYTES + 1)
            except FileNotFoundError:
                return None
            except OSError as exc:
                raise StoreError("Không đọc được phiên đã lưu") from exc
            
            try:
                # Kiểm tra kích thước và đầu nhận diện, nếu đầu nhận diện khác thì hủy
                if len(blob) > self.MAX_BYTES or not blob.startswith(self.MAGIC):
                    raise StoreError("Tệp phiên không hợp lệ")

                # Cắt bỏ phần nhận diện và tiến hành giải mã
                plaintext = self.protector.unprotect(blob[len(self.MAGIC):])
                return self._validate(json.loads(plaintext.decode("utf-8")))
            
            except StoreError:
                raise
            except Exception as exc:
                raise StoreError("Không giải mã được phiên; hãy đăng nhập lại") from exc

    def save(self, record):
        """
        Ghi phiên đăng nhập đã mã hóa
        """
        # Trong suốt quá trình thao tác thì giữ khóa
        with self._lock:
            try:
                # Validation dữ liệu và lấy các trường cần thiết
                validated = self._validate(dict(record))
                # Chuyển Dictionary thành chuỗi JSON và sau đó lại chuyển tiếp thành bytes UTF-8
                plaintext = json.dumps(validated, ensure_ascii=False).encode("utf-8")
                # Mã hóa bytes utf-8 thành DPAPI
                ciphertext = self.protector.protect(plaintext)
                # Ghép thêm chuỗi nhận diện
                blob = self.MAGIC + ciphertext
                # Kiểm tra độ dài
                if len(blob) > self.MAX_BYTES:
                    raise StoreError("Phiên quá lớn")
                # Ghi file đã mã hóa vào window
                atomic_write(self.path, blob)

            except StoreError:
                raise
            except Exception as exc:
                raise StoreError("Không lưu được phiên đã mã hóa") from exc

    def clear(self):
        """
        Xóa file phiên
        """
        with self._lock:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as exc:
                raise StoreError("Không xóa được phiên đã lưu") from exc


def scrub_legacy_config(path):
    """
    Xóa password/raw token cũ; KHÔNG nhập token cũ vào phiên tự đăng nhập.  
    Không tạo backup chứa bí mật; không tự ghi đè JSON hỏng.  
    Việc xóa local không thu hồi token đã lộ trên server.  
    """
    path = Path(path)
    try:
        # Đọc JSON cũ, giới hạn khoảng một triệu ký tự. Vì mở ở chế độ văn bản, đây là giới hạn ký tự đọc, không phải chính xác một MiB dữ liệu UTF-8
        with path.open("r", encoding="utf-8") as stream:
            text = stream.read(1024 * 1024 + 1)
    # Nếu không có file thì không cần làm gì hết
    except FileNotFoundError:
        return

    # Nếu quá lớn thì lỗi
    if len(text) > 1024 * 1024:
        raise StoreError("Cấu hình cũ quá lớn")

    # Bắt đầu phân tích
    try:
        config = json.loads(text)
        # Phải là dict và trường login phải là danh sách
        if not isinstance(config, dict) or not isinstance(config.get("Login", []), list):
            raise ValueError()

        # Biến đánh dấu đã thay đổi dữ liệu
        changed = False
        # Duyệt từng tài khoản
        for account in config.get("Login", []):
            if not isinstance(account, dict):
                raise ValueError()

            # Lấy ra 2 key password và session để không còn lưu
            for key in ("password", "session_token"):
                if key in account:
                    account.pop(key)
                    changed = True

        if changed:
            atomic_write(path, json.dumps(config, ensure_ascii=False, indent=2).encode("utf-8"))
            
    except (ValueError, TypeError) as exc:
        raise StoreError("Cấu hình cũ hỏng: cần xử lý tệp này thủ công") from exc
