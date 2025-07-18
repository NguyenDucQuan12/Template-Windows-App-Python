import os
import sys
from utils.constants import IMAGE

def resource_path(relative_path):
    """ Trả về đường dẫn đến file tài nguyên khi đóng gói với PyInstaller """
    try:
        # Khi chạy ứng dụng từ file .exe
        base_path = sys._MEIPASS
    except Exception:
        # Khi chạy từ mã nguồn Python
        base_path = os.path.abspath(".")

    full_path = os.path.join(base_path, relative_path)

    # Kiểm tra tệp tin có tồn tại không trước khi trả về đường dẫn
    if not os.path.exists(full_path):

        # Kiểm tra đuôi tệp tin
        if full_path.endswith(('.png', '.jpg', '.jpeg', '.ico')):
            # Nếu là hình ảnh thì trả về đường dẫn mặc định
            return IMAGE["DEFAULT_IMG"]
        # Nếu không phải là hình ảnh thì trả về none
        else:
            # Nếu không phải là tệp tin văn bản thì trả về None
            return None
        
    return full_path