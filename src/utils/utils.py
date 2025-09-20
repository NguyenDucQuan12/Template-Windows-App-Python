import pyodbc
from ctypes import windll
import re

def get_odbc_drivers_for_sql_server():
    """
    Lấy danh sách các ODBC Driver đã cài trên máy tính
    """
    # Lấy danh sách tất cả các ODBC drivers cài đặt trên hệ thống
    drivers = pyodbc.drivers()

    # Biểu thức chính quy để tìm các driver có dạng "ODBC Driver xx for SQL Server"
    pattern = re.compile(r"ODBC Driver \d+ for SQL Server")
    
    # Lọc các driver có tên phù hợp với biểu thức chính quy
    odbc_drivers = [driver for driver in drivers if pattern.match(driver)]
    
    return odbc_drivers

def get_screen_dpi():
    """
    Tính toán DPI của màn hình thiết bị Windows
    Bởi customTkinter hỗ trợ tự động điều chỉnh giao diện tùy theo DPI của màn hình máy tính  
    Còn Treeview của Tkinter thì không hỗ trợ tự động điều chỉnh DPI, nên cần phải tính toán giá trị DPI của màn hình rồi đưa ra font size phù hợp
    """
    base_font_size = 10  # Kích thước font mặc định cho DPI 96 (Là scale 100% trên Windows)
    base_row_height = 28  # Kích thước font mặc định cho DPI 96 (Là scale 100% trên Windows)

    LOGPIXELSX = 88  # Horizontal DPI
    LOGPIXELSY = 90  # Vertical DPI

    user32 = windll.user32
    user32.SetProcessDPIAware()  # Important for accurate results
    dc = user32.GetDC(0)
    horizontal_dpi = windll.gdi32.GetDeviceCaps(dc, LOGPIXELSX)
    vertical_dpi = windll.gdi32.GetDeviceCaps(dc, LOGPIXELSY)
    user32.ReleaseDC(0, dc)

    # Tính toán kích thước font dựa trên DPI
    font_size = int(base_font_size * (vertical_dpi / 96))
    row_height = int(base_row_height * (vertical_dpi / 96))
    return font_size, row_height