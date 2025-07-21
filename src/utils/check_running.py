
import psutil

def check_if_running(exe_name):
    # Kiểm tra nếu ứng dụng đã chạy dựa trên tên tệp .exe
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            # Kiểm tra tiến trình đang chạy là tệp exe của ứng dụng
            if exe_name.lower() in proc.info['name'].lower():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False