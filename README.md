
# Tạo môi trường ảo

Chạy lệnh sau để tạo môi trường ảo:  

```python
python -m venv .venv_source --prompt="virtual environment source"
```

Kích hoạt môi trường ảo:  
```python
.venv_source\Scripts\activate
```

Cài đặt các thư viện cần thiết:  
```python
python -m pip install -r requirements.txt
```



# Tạo CSDL

Đầu tiên ta cần tạo 1 CSDL trước có tên là `DucQuanApp`:  
```SQL
-- Tạo database mới
CREATE DATABASE DucQuanApp
```
Sau khi tạo xong Database ta cần chuuyeern đến `DucQuanApp` thì mới có thể thực hiện thao tác đối với CSDL này:  
```SQL
-- Chuyển vào database DucQuanApp
USE DucQuanApp
```
Sau đó ta tiến hành tạo bảng chứa thông tin đăng nhập có tên là `Users` và các trường thông tin cần thiết:  
```SQL
-- Tạo bảng Users
CREATE TABLE Users (
	User_Name NVARCHAR(500),
	Email NVARCHAR(500) UNIQUE, --Ràng buộc Email là duy nhất trong bảng
	Password NVARCHAR(500),
	Salt_Password NVARCHAR(500),
	Activate DATETIME,
	Privilege NVARCHAR(500),
	OTP NVARCHAR(80),
	Expired_OTP DATETIME,
	Status NVARCHAR(200)
)
```

Nếu lúc tạo bảng mà quên thêm ràng buộc cho cột `Email` thì sử dụng lệnh sau:  
```SQL
-- Thêm ràng buộc cho bảng nếu quên lúc tạo
ALTER TABLE Users
ADD CONSTRAINT UQ_Email UNIQUE (Email)
```

Sau khi đã có bảng thì thêm 1 dòng dữ liệu ban đầu để đăng nhập:  
```SQL
-- Thêm dữ liệu mới vào bảng
INSERT INTO Users
(
    User_Name,
    Email,
    Password,
    Salt_Password,
    Activate,
    Privilege,
    OTP,
    Expired_OTP,
    Status
)
VALUE (
    N'Nguyễn Đức Quân',
    'nguyenducquan2001@gmail.com',
    'password_hashed',
    'salt_password',
    GETDATE(), -- Lấy thời gian hiện tại
    'Admin',
    'hst283r',
    DATEADD(HOUR, 1, GETDATE()), -- Thêm thời gian 1 tiếng cho thời gian hiện tại
    NULL
)
```

> Lưu ý giá trị 2 trường `Password` và `Salt_Password` phải tuân thủ cách mã hóa ở [tệp mã hóa](src/services/hash.py).  

