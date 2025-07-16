# import bcrypt # pip install bcrypt
import hashlib
import os
import base64
from Crypto.Cipher import AES   # pip install pycryptodome
from Crypto.Util.Padding import pad, unpad
"""
Sự khác nhau phương thức thể hiện và phương thức tĩnh
Class Hash đang được coi là phuong thức tĩnh, bởi 
Với @staticmethod, thì tôi có thể gọi phương thức mà không cần tạo 1 đối tượng : hashed_password = Hash.bcrypt(password)
Còn với phương thức thể hiện, bạn thêm tham số self vào các hàm thì bạn cần tạo 1 thể hiện trước khi gọi hàm:
hash_instance = Hash()
hashed_password = hash_instance.bcrypt(password)

Việc sử dụng self hay @staticmethod phụ thuộc vào yêu cầu cụ thể của phương thức. Nếu phương thức không cần truy cập
hoặc thay đổi trạng thái của đối tượng hoặc lớp, việc sử dụng @staticmethod sẽ giúp mã nguồn rõ ràng và dễ hiểu hơn. 
Ngược lại, nếu phương thức cần truy cập hoặc thay đổi trạng thái của đối tượng, việc sử dụng self là phù hợp.
"""

class Hash:
    """
    Mã hóa mật khẩu bằng hàm băm Scrypt (một chiều) và AES (có thể giải mã). 

    Scrypt (Băm một chiều - không thể giải mã)

    Bảo mật cao, dùng để kiểm tra mật khẩu khi người dùng đăng nhập.
    Không thể khôi phục lại mật khẩu ban đầu.

    AES-256 (Mã hóa hai chiều - có thể giải mã)

    Dùng khi cần lưu trữ mật khẩu để có thể lấy lại.
    Mật khẩu có thể giải mã khi cần.
    """

    @staticmethod
    def scrypt(password):
        """
        Mã hóa mật khẩu sử dụng thuật toán scrypt
        Trả về chuỗi mã hóa cùng với salt của mật khẩu đó
        Mỗi mật khẩu sẽ được băm với một salt ngẫu nhiên và duy nhất
        """
        try:
            # Chuyển đổi mật khẩu sang bytes
            pwd_bytes = password.encode("utf-8")
            
            # Tạo salt ngẫu nhiên (16 byte)
            salt = os.urandom(16)
            
            # Băm mật khẩu với scrypt
            hashed_password = hashlib.scrypt(
                pwd_bytes,
                salt=salt,
                n=16384,  # Số vòng lặp (cost factor)
                r=8,      # Độ rộng khối
                p=1,      # Số luồng
                dklen=64  # Độ dài khóa băm
            )
            
            # Trả về salt và hashed_password dưới dạng hex để lưu trữ
            return salt.hex(), hashed_password.hex()
        except Exception as e:
            # Xử lý lỗi nếu có
            print(f"Error hashing password: {e}")
            return None

    @staticmethod
    def verify(stored_salt, stored_hashed_password, input_password):
        """
        Kiểm tra chuỗi đưa vào có trùng với mật khẩu đã mã hóa không
        Sử dụng một mã salt đã lưu trữ từ lúc scrypt để kiểm tra.
        """
        try:
            # Chuyển đổi salt và hashed_password từ hex về bytes
            salt = bytes.fromhex(stored_salt)
            stored_hashed_password = bytes.fromhex(stored_hashed_password)
            
            # Chuyển đổi mật khẩu đầu vào sang bytes
            input_password_bytes = input_password.encode("utf-8")
            
            # Băm mật khẩu đầu vào với cùng salt và tham số scrypt
            input_hashed_password = hashlib.scrypt(
                input_password_bytes,
                salt=salt,
                n=16384,
                r=8,
                p=1,
                dklen=64
            )
            
            # So sánh băm đầu ra với băm đã lưu trữ
            return input_hashed_password == stored_hashed_password
        except Exception as e:
            # Xử lý lỗi nếu có
            print(f"Error verifying password: {e}")
            return False
    
    @staticmethod
    def generate_aes_key():
        """
        Tạo một khóa AES ngẫu nhiên (32 bytes - 256 bit).
        Mỗi mật khẩu sẽ có một khóa AES riêng.
        """
        return os.urandom(32)  # 256-bit key

    @staticmethod
    def encrypt_password(password):
        """
        Mã hóa mật khẩu bằng AES-256.
        Trả về (mật khẩu đã mã hóa, khóa bí mật AES).
        """
        try:
            key = Hash.generate_aes_key()  # Mỗi mật khẩu có khóa riêng
            cipher = AES.new(key, AES.MODE_CBC)
            encrypted_bytes = cipher.encrypt(pad(password.encode("utf-8"), AES.block_size))
            
            # Trả về IV (khởi tạo) + dữ liệu đã mã hóa, cùng với khóa AES
            encrypted_data = base64.b64encode(cipher.iv + encrypted_bytes).decode("utf-8")
            aes_key = base64.b64encode(key).decode("utf-8")  # Chuyển khóa AES thành base64 để dễ lưu trữ
            
            return encrypted_data, aes_key  # Trả về cả dữ liệu đã mã hóa và khóa bí mật
        except Exception as e:
            print(f"Error encrypting password: {e}")
            return None, None

    @staticmethod
    def decrypt_password(encrypted_password, aes_key):
        """
        Giải mã mật khẩu AES-256 bằng khóa bí mật.
        """
        try:
            # Chuyển đổi dữ liệu về dạng bytes
            key = base64.b64decode(aes_key)
            encrypted_data = base64.b64decode(encrypted_password)

            iv = encrypted_data[:AES.block_size]  # Lấy IV từ dữ liệu
            encrypted_bytes = encrypted_data[AES.block_size:]

            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted_bytes = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
            
            return decrypted_bytes.decode("utf-8")
        except Exception as e:
            print(f"Error decrypting password: {e}")
            return None

if __name__ == "__main__":
    # Tạo một mật khẩu
    password = "my_secure_password"

    # 1️⃣ Băm mật khẩu (KHÔNG thể giải mã)
    salt, hashed_password = Hash.scrypt(password)
    print("Scrypt Hashed Password:", hashed_password)

    # Kiểm tra mật khẩu
    is_valid = Hash.verify(salt, hashed_password, "my_secure_password")
    print("Mật khẩu đúng không?", is_valid)  # Kết quả: True

    # 2️⃣ Mã hóa mật khẩu (CÓ THỂ giải mã)
    encrypted_password, aes_key = Hash.encrypt_password(password)
    print("Mật khẩu đã mã hóa:", encrypted_password)
    print("Khóa bí mật AES:", aes_key)

    # Giải mã lại
    decrypted_password = Hash.decrypt_password(encrypted_password, aes_key)
    print("Mật khẩu sau khi giải mã:", decrypted_password)
