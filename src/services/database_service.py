import pyodbc
import logging
import re
from datetime import datetime, timedelta


# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
import os,sys
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)

from services.hash import Hash
from utils.constants import *

pyodbc.pooling = True  # Enable connection pooling for better performance
logger = logging.getLogger(__name__)


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

class My_Database:
    # def __init__(self, server_name="10.239.1.162", database_name="DB_QLNS_HR_APP", user_name="quannd", password="quannd"):
    def __init__(self, server_name="localhost", database_name="DucQuanApp", user_name="ducquan_user", password="123456789"):
        """
        Khởi tạo đối tượng kết nối đến cơ sở dữ liệu với chuỗi kết nối.
        """
        # Tải danh sách ODBC Driver cho SQL Server
        self.database_name = database_name
        odbc_drivers = get_odbc_drivers_for_sql_server()
        if odbc_drivers is None or not odbc_drivers:
            logger.error("Không phát hiện driver ODBC để kết nối tới CSDL")
            return

        self.connection_string = (
            f"DRIVER={odbc_drivers[0]};"
            f"SERVER={server_name};"
            f"DATABASE={database_name};"
            f"UID={user_name};"
            f"PWD={password};"
            "TrustServerCertificate=yes;"
        )

    def _connect(self):
        """Hàm kết nối đến DB với connection pooling."""
        try:
            conn = pyodbc.connect(self.connection_string)
            logger.debug("Kết nối đến cơ sở dữ liệu thành công.")
            return conn
        except Exception as e:
            logger.error(f"Không thể kết nối đến cơ sở dữ liệu: {e}")
            return None

    def _check_connection(self):
        """Kiểm tra kết nối đến DB trước khi thực hiện các truy vấn hoặc cập nhật."""
        conn = self._connect()
        if conn is None:
            logger.error(f"Không thể kết nối đến cơ sở dữ liệu {self.database_name}. Vui lòng kiểm tra lại kết nối.")
            return False
        conn.close()
        return True

    def _execute_query(self, query, params=None):
        """
        Thực thi câu lệnh SELECT với kiểm soát lỗi, bảo mật và kết quả rõ ràng.
        """
        response = {
            "success": False,
            "message": "",
            "data": None
        }

        conn = self._connect()
        if conn:
            try:
                with conn.cursor() as cursor:
                    # Sử dụng parameterized query để tránh SQL Injection
                    if params:
                        cursor.execute(query, params)
                    else:
                        cursor.execute(query)

                    # Lấy tất cả kết quả trả về
                    rows = cursor.fetchall()

                    # Trả kết quả vào json
                    response["data"] = rows if rows else []
                    response["success"] = True
                    response["message"] = "Truy vấn thành công." if rows else "Không có dữ liệu trả về."

            except pyodbc.Error as e:
                response["message"] = f"Lỗi truy vấn cơ sở dữ liệu: {str(e)}."

            except Exception as e:
                response["message"] = f"Lỗi truy vấn cơ sở dữ liệu: {str(e)}."

            finally:
                conn.close()
        else:
            response["message"] = "Không thể kết nối tới CSDL."

        # Trả về kết quả cuối cùng
        return response

# ------------------ Bảng Users ------------------
# Bởi vì User là 1 từ khóa đã định nghĩa nên cần cho nó vào ngoặc vuông để hiểu đó là tên bảng: FROM [User]
# Đổi lại tên bảng là Users để tránh nhầm lẫn với từ khóa đã định nghĩa: FROM Users

    def _check_user_exists(self, email):
        """
        Kiểm tra người dùng có tồn tại trong CSDL hay không.
        """
        query = "SELECT COUNT(*) FROM Users WHERE Email = ?"
        params = (email,)
        result = self._execute_query(query, params)
        
        return result["data"][0][0] > 0

    def get_information_all_user(self):
        """
        Truy vấn thông tin tất cả người dùng.
        """
        query = "SELECT User_Name, Email, Activate, Privilege, OTP, Expired_OTP FROM Users"
        result = self._execute_query(query)

        # Trả về kết quả rõ ràng
        return result

    def get_username(self, email):
        """
        Lấy tên người dùng thông qua email
        """
        query = "SELECT User_Name FROM Users WHERE Email = ?"
        params = (email,)
        result = self._execute_query(query, params)

        # Trả về kết quả rõ ràng
        return result
    
    def get_password_salt_password_privilege_user(self, email):
        """
        Lấy mật khẩu, salt mã hóa và quyền hạn của người dùng
        """
        query = "SELECT Password, Salt_Password, Activate, Privilege FROM Users WHERE Email = ?"
        params = (email,)
        result = self._execute_query(query, params)

        # Trả về kết quả rõ ràng
        return result
    
    def get_otp_and_expired_time(self, email):
        """
        Lấy mã OTP và thời gian hết hạn của nó
        """
        get_otp_and_time_expired_query ="""
            SELECT OTP, Expired_OTP FROM Users WHERE Email = ?
            """
        params = (email,)
        result = self._execute_query(get_otp_and_time_expired_query, params)

        # Trả về kết quả rõ ràng
        return result

    def activate_user(self, email, activate=True):
        """
        Kích hoạt hoặc hủy kích hoạt tài khoản người dùng
        """
        conn = self._connect()
        response = {
            "success": False,
            "message": ""
        }

        if conn:
            try:
                with conn.cursor() as cursor:
                    if activate:
                        activate_user_query = """
                            UPDATE Users
                            SET Activate = GETDATE()
                            WHERE Email = ? 
                        """
                    else:
                        activate_user_query = """
                            UPDATE Users
                            SET Activate = NULL
                            WHERE Email = ? 
                        """
                    params_update = (email,)
                    cursor.execute(activate_user_query, params_update)
                    conn.commit()

                    # Kiểm tra xem có hàng nào được áp dụng không
                    if cursor.rowcount > 0:
                        response["success"] = True
                        response["message"] = f"Kích hoạt/hủy kích hoạt thành công người dùng có địa chỉ: {email}."
                    else:
                        response["success"] = False
                        response["message"] = "Không tìm thấy tài khoản hoặc không có tài khoản nào được kích hoạt."

            except Exception as e:
                conn.rollback()
                response["success"] = False
                response["message"] = f"Lỗi khi kích hoạt/hủy kích hoạt tài khoản: {str(e)}"

            finally:
                conn.close()
        else:
            response["success"] = False
            response["message"] = "Không thể kết nối đến cơ sở dữ liệu."

        return response
        
    def create_new_user(self, username, email, password, privilege="User"):
        """
        Thêm người dùng mới vào CSDL
        """
        response = {
            "success": False,
            "message": ""
        }
        
        # Mã hóa mật khẩu trước khi đưa vào CSDL
        salt_password, password_hashed = Hash.scrypt(password = password)

        # Bởi vì User là 1 từ khóa đã định nghĩa nên cần cho nó vào ngoặc vuông để hiểu đó là tên bảng
        query = """
            INSERT INTO Users (User_Name, Email, Password, Salt_Password, Privilege)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (username, email, password_hashed, salt_password, privilege)
        conn = self._connect()
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute(query, params)
                    conn.commit()

                    if cursor.rowcount > 0:
                        response["success"] = True
                        response["message"] = f"Tạo mới tài khoản người dùng thành công có địa chỉ: {email}"
                    else:
                        response["success"] = False
                        response["message"] = f"Không thể tạo mới tài khoản cho người dùng {email}"
                    
            except Exception as e:
                response["success"] = False
                response["message"] = f"Lỗi khi tạo tài khoản mới cho người dùng {email}: {str(e)}"

            finally:
                conn.close()
        else:
            response["success"] = False
            response["message"] = f"Không thể tạo mới tài khoản cho người dùng {email}"               
        
        return response

    def update_password_user(self, email, password=None):
        """
        Cập nhật mật khẩu mới cho người dùng
        """
        # Mã hóa mật khẩu trước khi đưa vào CSDL
        salt_password, password_hashed = Hash.scrypt(password = password)

        # Bắt đầu một kết nối
        conn = self._connect()

        # Biến trả kết quả
        response = {
            "success": False,
            "message": ""
        }

        if conn:
            try:
                # Bắt đầu transaction
                with conn.cursor() as cursor:
                    # Cập nhật mật khẩu người dùng
                    update_password_query = """
                        UPDATE Users
                        SET Password = ?, Salt_Password = ?
                        WHERE Email = ? 
                    """
                    params_update = (password_hashed, salt_password, email)
                    cursor.execute(update_password_query, params_update)
                    conn.commit()

                    # Kiểm tra xem có hàng nào được áp dụng không
                    if cursor.rowcount > 0:
                        response["success"] = True
                        response["message"] = f"Đã cập nhật mật khẩu mới thành công cho người dùng: {email}."
                    else:
                        response["success"] = False
                        response["message"] = f"Không thể cập nhật mật khẩu mới cho người dùng: {email}"

            except Exception as e:
                # Nếu có lỗi, rollback toàn bộ transaction
                conn.rollback()

                response["success"] = False
                response["message"] = f"Lỗi khi cập nhật mật khẩu cho người dùng {email}: {e}"

            finally:
                conn.close()
        else:
            response["success"] = False
            response["message"] = f"Không thể kết nối tới CSDL"

        return response

    def update_OTP_and_time_expired(self, email, OTP, time_expired):
        """
        Cập nhật mã OTP và thời gian hết hạn của mã OTP này
        """
        # Bắt đầu một kết nối
        conn = self._connect()

        # Biến trả kết quả
        response = {
            "success": False,
            "message": ""
        }

        if conn:
            try:
                # Bắt đầu transaction
                with conn.cursor() as cursor:
                    # Cập nhật mã OTP và thời gian hết hạn của nó
                    update_OTP_query = """
                        UPDATE Users
                        SET OTP = ?, Expired_OTP = ?
                        WHERE Email = ? 
                    """
                    params_update = (OTP, time_expired, email)
                    cursor.execute(update_OTP_query, params_update)
                    conn.commit()

                    # Kiểm tra xem có hàng nào được áp dụng không
                    if cursor.rowcount > 0:
                        response["success"] = True
                        response["message"] = f"Cập nhật mã OTP thành công cho người dùng có địa chỉ: {email}."
                    else:
                        response["success"] = False
                        response["message"] = f"Không có người dùng nào được cập nhật mã OTP với địa chỉ: {email}"
            except Exception as e:
                # Nếu có lỗi, rollback toàn bộ transaction
                conn.rollback()

                response["success"] = False
                response["message"] = f"Lỗi khi cập nhật mã OTP cho người dùng có địa chỉ {email}: {e}"
                
            finally:
                conn.close()
        else:
            response["success"] = False
            response["message"] = f"Không thể kết nối tới CSDL"
            
        return response

    def delete_account_user(self, email):
        """
        Xóa tài khoản người dùng có email truyền vào
        """
        # Biến trả kết quả
        response = {
            "success": False,
            "message": ""
        }

        # Bắt đầu một kết nối
        conn = self._connect()
        if conn:
            try:
                # Bắt đầu transaction
                with conn.cursor() as cursor:
                    # Cập nhật mã OTP và thời gian hết hạn của nó
                    delete_account_query = """
                        DELETE TOP(1) FROM Users
                        WHERE Email = ? 
                    """
                    params_update = (email)
                    cursor.execute(delete_account_query, params_update)
                    conn.commit()

                    # Kiểm tra xem có hàng nào được áp dụng không
                    if cursor.rowcount > 0:
                        response["success"] = True
                        response["message"] = f"Xóa tài khoản thành công người dùng có địa chỉ: {email}."
                    else:
                        response["success"] = False
                        response["message"] = f"Không có người dùng nào được xóa với địa chỉ: {email}"
                
            except Exception as e:
                # Nếu có lỗi, rollback toàn bộ transaction
                conn.rollback()

                response["success"] = False
                response["message"] = f"Lỗi khi xóa tài khoản người dùng {email}: {e}"
            
            finally:
                conn.close()
        else:
            response["success"] = False
            response["message"] = f"Không thể kết nối tới CSDL"
            
        return response

    def change_role_user(self, privilege, email):
        """
        Cập nhật quyền hạn của người dùng
        """
       # Biến trả kết quả
        response = {
            "success": False,
            "message": ""
        }

        # Bắt đầu một kết nối
        conn = self._connect()
        if conn:
            try:
                # Bắt đầu transaction
                with conn.cursor() as cursor:
                    # Cập nhật mã OTP và thời gian hết hạn của nó
                    update_privilege_account_query = """
                        UPDATE Users
                        SET Privilege = ?
                        WHERE Email = ?
                    """
                    params_update = (privilege, email)
                    cursor.execute(update_privilege_account_query, params_update)
                    conn.commit()

                    # Kiểm tra xem có hàng nào được áp dụng không
                    if cursor.rowcount > 0:
                        response["success"] = True
                        response["message"] = f"Cập nhật quyền hạn thành công cho người dùng {email}: {privilege}."
                    else:
                        response["success"] = False
                        response["message"] = f"Không có người dùng nào được cập nhật quyền hạn mới với địa chỉ: {email}"

            except Exception as e:
                # Nếu có lỗi, rollback toàn bộ transaction
                conn.rollback()
                response["success"] = False
                response["message"] = f"Lỗi khi cập nhật quyền hạn mới cho người dùng có địa chỉ {email}: {e}"
            
            finally:
                conn.close()
        
        else:
            response["success"] = False
            response["message"] = f"Không thể kết nối tới CSDL"
            
        return response