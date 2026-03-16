import os
import psutil

def check_if_running_by_name(exe_name: str) -> bool:
    """
    Kiểm tra app đã chạy chưa dựa trên *tên process* (vd: MyApp.exe).
    """
    current_pid = os.getpid()               # PID của process hiện tại (chính instance đang chạy)
    target_name = exe_name.casefold()       # casefold() chắc hơn lower() cho việc so sánh không phân biệt hoa/thường

    # Duyệt tất cả process đang chạy và chỉ lấy các trường cần thiết để nhanh hơn
    for proc in psutil.process_iter(attrs=["pid", "name"]):
        try:
            pid = proc.info.get("pid")

            # Bỏ qua chính process hiện tại để không "tự phát hiện mình"
            if pid == current_pid:
                continue

            name = proc.info.get("name")

            # Nếu không đọc được name (None/""), bỏ qua để tránh lỗi .casefold()
            if not name:
                continue

            # So sánh chính xác bằng nhau (tránh dùng "in" để không match nhầm)
            if name.casefold() == target_name:
                return True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            # Process có thể biến mất ngay lúc đang duyệt hoặc không đủ quyền để đọc thông tin
            continue

    return False


def check_if_running_by_exe_path() -> bool:
    """
    Kiểm tra app đã chạy chưa dựa trên *đường dẫn exe* của chính app hiện tại.

    Ý tưởng:
      - Lấy đường dẫn exe của instance hiện tại (process đang chạy)
      - Duyệt các process khác, nếu process nào có exe path trùng thì => đã có instance khác

    Ưu điểm:
      - Ít false-positive hơn so với kiểm tra theo tên
    Nhược điểm:
      - Có thể gặp AccessDenied khi đọc exe của process khác
      - Vẫn không chống race condition 100%
    """
    me = psutil.Process()                       # Process object của chính instance hiện tại
    my_pid = me.pid                             # PID hiện tại
    my_exe = me.exe()                           # Đường dẫn exe của instance hiện tại
    my_exe_norm = os.path.normcase(my_exe)      # Chuẩn hóa hoa/thường trên Windows để so sánh path

    # Có thể giới hạn theo user để tránh "đụng" app cùng tên của user khác (nếu máy có nhiều user/session)
    try:
        my_user = me.username()
    except psutil.Error:
        my_user = None

    for proc in psutil.process_iter(attrs=["pid", "exe", "username", "name"]):
        try:
            # Bỏ qua chính mình
            if proc.info.get("pid") == my_pid:
                continue

            # (Tuỳ chọn) Chỉ xét process cùng user để tránh nhầm với user khác
            if my_user and proc.info.get("username") and proc.info["username"] != my_user:
                continue

            exe = proc.info.get("exe")

            # Nếu không đọc được exe (None) thì có thể fallback sang name, nhưng cẩn thận false-positive
            if exe:
                if os.path.normcase(exe) == my_exe_norm:
                    return True

        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    return False