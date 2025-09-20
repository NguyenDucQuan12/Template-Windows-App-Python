# Tên phần mềm
APP_NAME_SYSTEM = "DucQuan"
APP_TITLE = "Nguyễn Đức Quân"
APP_FOLDER_LOG = "DucQuanLog"
APP_UPDATER = "Updater.exe"

# Màu sắc
COLOR = {
    "PRIMARY_COLOR": "#2c3e50",  # Màu chính
    "SECONDARY_COLOR": "#34495e",  # Màu phụ
    "BACKGROUND_COLOR": "#ecf0f1",  # Màu nền
    "TEXT_COLOR": "#2c3e50",  # Màu chữ
    "BUTTON_COLOR": "#3498db",  # Màu nút
    "DANGER_BUTTON_COLOR": "#e74c3c",  # Màu nút nguy hiểm
    "WARNING_BUTTON_COLOR": "#f1c40f",  # Màu nút cảnh báo
    "INFO_BUTTON_COLOR": "#8e44ad",  # Màu nút thông tin
    "HOVER_COLOR": "#2980b9",  # Màu khi hover
    "ERROR_COLOR": "#e74c3c",  # Màu lỗi
    "SUCCESS_COLOR": "#2ecc71",  # Màu thành công
    "WARNING_COLOR": "#f1c40f",  # Màu cảnh báo
    "INFO_COLOR": "#8e44ad",  # Màu thông tin
    "LIGHT_COLOR": "#ecf0f1",  # Màu sáng
    "DARK_COLOR": "#2c3e50",  # Màu tối
    "TRANSPARENT_COLOR": "#ffffff00",  # Màu trong suốt
    "BORDER_COLOR": "#bdc3c7",  # Màu viền
    "DISABLED_COLOR": "#95a5a6",  # Màu vô hiệu hóa
    "SELECTED_COLOR": "#3498db",  # Màu đã chọn
    "UNSELECTED_COLOR": "#bdc3c7",  # Màu chưa chọn
    "FOCUS_COLOR": "#2980b9",  # Màu khi có focus
    "ERROR_BACKGROUND_COLOR": "#f8d7da",  # Màu nền
    "SUCCESS_BACKGROUND_COLOR": "#d4edda",  # Màu nền thành công
    "WARNING_BACKGROUND_COLOR": "#fff3cd",  # Màu nền cảnh báo
    "INFO_BACKGROUND_COLOR": "#d1c4e9",  # Màu nền thông tin
    "LIGHT_BACKGROUND_COLOR": "#f0f0f0",  # Màu nền sáng
    "DARK_BACKGROUND_COLOR": "#2c3e50",  # Màu nền tối
    "HOVER_BACKGROUND_COLOR": "#ecf0f1",  # Màu nền khi hover
    "SELECTED_BACKGROUND_COLOR": "#3498db",  # Màu nền đã chọn
    "UNSELECTED_BACKGROUND_COLOR": "#bdc3c7",  # Màu nền chưa chọn
    "FOCUS_BACKGROUND_COLOR": "#2980b9",  # Màu nền khi có focus
    "DISABLED_BACKGROUND_COLOR": "#95a5a6",  # Màu nền vô hiệu hóa
    "BORDER_LIGHT_COLOR": "#dfe6e9",  # Màu viền sáng
    "BORDER_DARK_COLOR": "#2c3e50",  # Màu viền tối
    "BORDER_HOVER_COLOR": "#3498db",  # Màu viền khi hover
    "BORDER_SELECTED_COLOR": "#2980b9",  # Màu viền đã chọn
    "BORDER_UNSELECTED_COLOR": "#bdc3c7",  # Màu viền chưa chọn
    "BORDER_FOCUS_COLOR": "#2980b9",  # Màu viền khi có focus
    "BORDER_DISABLED_COLOR": "#95a5a6",  # Màu viền vô hiệu hóa
    "BORDER_ERROR_COLOR": "#e74c3c",  # Màu viền lỗi
    "BORDER_SUCCESS_COLOR": "#2ecc71",  # Màu viền thành công
    "BORDER_WARNING_COLOR": "#f1c40f",  # Màu viền cảnh báo
    "BORDER_INFO_COLOR": "#8e44ad",  # Màu viền thông tin
    "BORDER_LIGHT_BACKGROUND_COLOR": "#f0f0f0",  # Màu viền nền sáng
    "BORDER_DARK_BACKGROUND_COLOR": "#2c3e50",  # Màu viền nền tối
}


# Các tên của navigation
HOME_NAV = "Trang chủ"
CHAT_NAV = "Trò chuyện"
DATABASE_NAV = "Cơ sở dữ liệu"

# Quyền hạn
PERMISSION = {
    "ADMIN": "Admin",
    "USER": "User",
    "GUEST": "Guest"
}

LIST_PERMISSION = ["Admin", "User", "Guest"]

# Đường dẫn tới các tệp tin
FILE_PATH = {
    "LOGIN_CONFIG": 'src\\config\\login_information.json',
    "UPDATE_CONFIG": "data\\update_information.json"
}

# Đường dẫn tới các hình ảnh mặc định
IMAGE = {
    "DEFAULT_IMG": "assets\\images\\default\\not_found_image.png",
    "ICO_IMG": "assets\\images\\ico\\ico.ico",
    "NAVIGATION_LOGO_IMG": "assets\\images\\navigation\\logo_navigation.png",
    "HOME_NAVIGATION_LIGHT_IMG": "assets\\images\\navigation\\home_light.png",
    "HOME_NAVIGATION_DARK_IMG": "assets\\images\\navigation\\home_dark.png",
    "CHAT_NAVIGATION_LIGHT_IMG": "assets\\images\\navigation\\chat_light.png",
    "CHAT_NAVIGATION_DARK_IMG": "assets\\images\\navigation\\chat_dark.png",
    "DATABASE_NAVIGATION_LIGHT_IMG": "assets\\images\\navigation\\database_light.png",
    "DATABASE_NAVIGATION_DARK_IMG": "assets\\images\\navigation\\database_dark.png",
}


# Danh sách các cột trong bảng người dùng
ACCOUNT_TABLE_COLUMN_LIST = [
    "Người dùng", "Tài khoản", "Ngày kích hoạt", "Quyền hạn", "Mã OTP", "Thời gian hết hạn"
]
