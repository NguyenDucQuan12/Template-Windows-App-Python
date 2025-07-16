import sys
import os
import shutil
import datetime
import logging
from utils.constants import *

logger = logging.getLogger(__name__)

# Lấy đường dẫn đến thư mục AppData/Roaming của người dùng
appdata_dir = os.getenv('APPDATA')

# Tạo thời gian ghi log
today = str(datetime.datetime.now().strftime("%Y-%m-%d-%H-%M-%S")) #chua ngay thang nam cung voi gio phut giay
date_today = str(datetime.datetime.now().strftime("%d-%m-%y")) # chỉ chứa ngày tháng năm

# Số ngày lưu trữ log, nếu quá thời gian này thì tự động xóa tệp
LOG_EXPIRATION_DAYS = 15

# Định nghĩa thư mục chứa log: AppData/Roaming/LOG_FOLDER/log
log_root_dir = os.path.join(appdata_dir, APP_FOLDER_LOG, "log")

# Tạo thư mục chứa nhật ký theo ngày tháng năm, nếu thư mục đã tồn tại thì không tạo nữa
# C:\\Users\\238299\\AppData\\Roaming\QL nhân sự\\log\\03-03-25
save_dir_log = os.path.join(appdata_dir, APP_FOLDER_LOG, "log", date_today)
os.makedirs(save_dir_log, exist_ok=True)

# Tạo 2 tệp chứa log và các câu lệnh print nếu tồn tại
log_file_path = save_dir_log +"/log.log"
log_print_app = save_dir_log + "/system_out.log"

# Ghi tất cả các thông báo bằng phương thức print vào file log và các lỗi xuất hiện vào file log_print_app
# Bởi vì khi đóng gói ứng dụng thì sẽ không có terminal hiển thị các thông tin này, vì vậy cần lưu vào file
# Với phương thức open thì sẽ tự động tạo file log nếu nó chưa tồn tại
sys.stdout = open(log_print_app, encoding="utf-8", mode="a")
sys.stderr = open(log_print_app, encoding="utf-8", mode="a")

def delete_old_logs():
    """
    Xóa các thư mục log đã tồn tại quá thời gian lưu trữ cho phép.
    """
    # Không có thư mục log thì không cần làm gì
    if not os.path.exists(log_root_dir):
        return  

    # Lấy ngày hiện tại
    now = datetime.datetime.now()

    # Duyệt tất cả các thư mục con trong thư mục `log` chứa các thư mục log con
    for folder in os.listdir(log_root_dir):
        folder_path = os.path.join(log_root_dir, folder)

        # Kiểm tra nếu nó là thư mục (vì mỗi ngày là một thư mục riêng)
        if os.path.isdir(folder_path):
            try:
                # Lấy thời gian chỉnh sửa cuối cùng của thư mục
                folder_mod_time = datetime.datetime.fromtimestamp(os.stat(folder_path).st_mtime)

                # Kiểm tra nếu thư mục đã tồn tại quá 30 ngày
                if (now - folder_mod_time).days > LOG_EXPIRATION_DAYS:
                    # Xóa toàn bộ thư mục và nội dung bên trong
                    logger.info(f"🗑️ Xóa thư mục log cũ: {folder_path}")
                    # os.remove(folder_path)  # os gặp lỗi Access is denied, chuyển sang shutil
                    shutil.rmtree(folder_path)

            except Exception as e:
                logger.error(f"⚠️ Không thể xóa thư mục {folder_path}: {e}")

def change_log_file_path(logger_root: logging, new_log_file_path = None):
    """
    Thay đổi vị trí tệp log mà không thay đổi các thiết lập khác của logger.  
    Dùng cho trường hợp sang 1 ngày mới, tự động chuyển sang vị trí log mới

    - Nếu logger_root được truyền vào là `logger = logging.getLogger(__name__)` thì nó chỉ ảnh hưỡng mỗi tệp đó
    """
    # Nếu không chỉ định vị trí mới thì tự tạo thư mục theo ngày tháng năm
    if new_log_file_path is None:
        # data test: 
        # current_today = str((datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%d-%m-%y")) # Tăng thêm 1 ngày

        # Tạo thời gian ghi log
        current_today = str(datetime.datetime.now().strftime("%d-%m-%y"))
        # C:\\Users\\238299\\AppData\\Roaming\QLNS\\log\\03-03-25
        new_dir_log = os.path.join(appdata_dir, APP_FOLDER_LOG, "log", current_today)

        # Tạo 2 tệp chứa log và các câu lệnh print nếu tồn tại
        new_log_file_path = new_dir_log +"/log.txt"
        new_log_print_app = new_dir_log + "/system_out.txt"
    
    # Kiểm tra xem thư mục chứa log đã được tạo chưa, nếu chưa có thì mới thực hiện tạo và thay đổi log, nếu có thì bỏ qua
    if not os.path.exists(new_dir_log):

        # Khai báo là biến toàn cục để sử dụng biến log_file_path
        global log_file_path
        # Ghi log
        logger.info("Thay đổi vị trí lưu log mới từ: %s sang vị trí: %s", log_file_path, new_log_file_path)

        # Kiểm tra và xóa các thư mục cũ đã tồn tại quá lâu
        delete_old_logs()
        try:
            # Tao thư mục mới
            os.makedirs(new_dir_log)

            # Xóa tất cả các handler cũ của logger
            for handler in logger_root.handlers[:]:
                handler.close()  # Đóng handler cũ
                logger_root.removeHandler(handler)  # Xóa handler cũ

            # Tạo một FileHandler mới với vị trí tệp log mới
            file_handler = logging.FileHandler(new_log_file_path, mode='a', encoding='utf-8')
        
            # Định dạng cho log
            formatter = logging.Formatter('%(asctime)s %(levelname)s:\t %(filename)s - Line: %(lineno)d message: %(message)s',
                                           datefmt='%d/%m/%Y %I:%M:%S %p')
            file_handler.setFormatter(formatter)
        
            # Thêm FileHandler mới vào logger
            logger_root.addHandler(file_handler)
            
            # Thiết lập mức độ log (nếu cần thiết)
            logger_root.setLevel(logging.INFO)
            
            # Nếu đầu ra của các phương thức khác với mặc định, tức là đang được ghi ở 1 tệp nào đó, thì đóng nó để không gây rò rỉ tài nguyên
            # Đóng file cũ nếu đang redirect
            try:
                if sys.stdout not in (sys.__stdout__, sys.__stderr__):
                    sys.stdout.close()
            except Exception as e:
                logger.error("Không thể đóng print đầu ra mặc định: %s", e, exc_info=True)
            try:
                if sys.stderr not in (sys.__stdout__, sys.__stderr__):
                    sys.stderr.close()
            except Exception as e:
                logger.error("Không thể error đóng đầu ra mặc định: %s", e, exc_info=True)

            # Trả lại về mặc định trước khi mở file mới
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__

            # Mở file mới cho ngày mới
            sys.stdout = open(new_log_print_app, encoding="utf-8", mode="a")
            sys.stderr = open(new_log_print_app, encoding="utf-8", mode="a")

            # Đặt lại tên thư mục log
            # Khi thay đổi giá trị của biến toàn cục nằm trong hàm thì bắt buộc phải sử dụng khai báo global (Nếu không nó sẽ tự hiểu đây là biến cục bộ) 
            log_file_path = new_log_file_path
            return True
        
        except Exception as e:
            logger.error("Không thể thay đổi vị trí lưu tệp log. Lỗi: %s", e)
            return False
    
    else:
        # Nếu thư mục này đã tồn tại thì không làm gì cả
        return True