"""
Tệp tin kiểm tra chương trình có được mở hai lần không
"""
import ctypes
import multiprocessing
import sys
from contextlib import contextmanager
from ctypes import wintypes


class AlreadyRunningError(RuntimeError):
    """Một phiên bản khác của ứng dụng đang chạy."""


@contextmanager
def single_instance(name: str):
    """
    Chỉ cho phép một phiên bản chạy trong phạm vi tên mutex.

    Phải giữ context này suốt thời gian ứng dụng hoạt động.
    Chỉ hỗ trợ Windows.
    """
    if sys.platform != "win32":
        raise RuntimeError("single_instance chỉ hỗ trợ Windows.")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (
        ctypes.c_void_p,   # Thuộc tính bảo mật mặc định
        wintypes.BOOL,     # Có lấy quyền sở hữu mutex hay không
        wintypes.LPCWSTR,  # Tên mutex
    )
    create_mutex.restype = wintypes.HANDLE

    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (wintypes.HANDLE,)
    close_handle.restype = wintypes.BOOL

    ERROR_ALREADY_EXISTS = 183

    ctypes.set_last_error(0)
    handle = create_mutex(None, False, name)
    error = ctypes.get_last_error()

    if not handle:
        # Không tạo/mở được mutex: báo lỗi, không tự cho app chạy tiếp.
        raise ctypes.WinError(error)

    try:
        if error == ERROR_ALREADY_EXISTS:
            raise AlreadyRunningError("Ứng dụng đã được mở ở một phiên bản khác.")
        yield
    finally:
        close_handle(handle)


def run_app():
    """
    Đặt phần khởi tạo và vòng lặp chính của ứng dụng tại đây.
    Ví dụ: root.mainloop() hoặc app.exec().
    """
    print("Ứng dụng đang chạy.")
    input("Nhấn Enter để thoát...")


def main() -> int:
    """
    Ví dụ chạy thử
    """
    # Giữ tên này cố định giữa các lần mở ứng dụng.
    mutex_name = r"Local\Quan.SingleInstance"

    try:
        with single_instance(mutex_name):
            run_app()

    except AlreadyRunningError as exc:
        print(exc)
        return 0

    return 0

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
