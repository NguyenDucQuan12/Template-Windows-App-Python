from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import logging
import re
import secrets
import uuid
import pyodbc

from services.hash import Hash
pyodbc.pooling = True  # Phải thiết lập trước connection đầu tiên của process.
logger = logging.getLogger(__name__)


class DatabaseError(RuntimeError):
    """Lỗi sạch; không chứa SQL, tham số, mật khẩu hay connection string."""


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

    return sorted(odbc_drivers)

def _text(value, name, maximum, *, strip=True):
    """
    Validation chuỗi
    """
    if not isinstance(value, str):
        raise ValueError(f"{name} phải là chuỗi")

    # Cắt bỏ khoảng trắng bai bên nếu True
    # Trong 1 số trường hợp như password " abc123  " thì để nguyên
    value = value.strip() if strip else value
    if not value or len(value) > maximum or "\x00" in value:
        raise ValueError(f"{name} rỗng hoặc vượt giới hạn {maximum}")

    return value


def _token_hash(token):
    """
    Hash chuỗi token để lưu vào DB
    """
    # Token ngẫu nhiên có entropy cao: SHA-256 dùng cho TOKEN, không cho password.
    token = _text(token, "Token", 8192, strip=False)
    return hashlib.sha256(token.encode("utf-8")).digest()  # 32 byte, không raw token.


def _utc(value):
    """
    Biến datetime `datetime(2026, 9, 14, 14, 30)` thành thời gian UTC `2026-09-14 14:30 UTC`
    """
    if not isinstance(value, datetime):
        raise DatabaseError("DB trả thời gian sai định dạng")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class MyDatabase:
    """
    Lớp kết nối tới CSDL
    """
    def __init__(self, server_name="localhost", database_name="DucQuanApp", user_name="ducquan_user",
                 password="123456789", *, connect_timeout=5, query_timeout=15,
                 allow_legacy_otp=True):
        """
        connector chỉ dành cho unit test. Không dùng sys.path.append hay import *.
        """
        # Tải danh sách ODBC Driver cho SQL Server
        self.database_name = database_name
        odbc_drivers = get_odbc_drivers_for_sql_server()
        if odbc_drivers is None or not odbc_drivers:
            logger.error("Không phát hiện driver ODBC để kết nối tới CSDL")
            return

        self._connection_string = (
            f"DRIVER={odbc_drivers[-1]};"
            f"SERVER={server_name};"
            f"DATABASE={database_name};"
            f"UID={user_name};"
            f"PWD={password};"
            "TrustServerCertificate=yes;"
        )
        # Timeout cho kết nối DB và thời gian truy vấn
        self._connect_timeout, self._query_timeout = connect_timeout, query_timeout
        self.allow_legacy_otp = allow_legacy_otp

    def _connect(self):
        """
        Mở kết nối tới CSDL
        """
        conn = pyodbc.connect(self._connection_string, timeout=self._connect_timeout,
                               autocommit=False)
        try:
            conn.timeout = self._query_timeout
            return conn
        except Exception: # pylint: disable=broad-except
            conn.close()
            raise

    @contextmanager
    def _transaction(self):
        """
        Một connection/cursor riêng mỗi thao tác; đóng trả pool cả khi lỗi.  
        Thành công -> commit; bất kỳ lỗi nào -> rollback; không retry ghi tự động.  
        """
        conn = cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            # nếu có runtime SQL error đủ nghiêm trọng thì transaction nên bị abort thay vì để transaction ở trạng thái dở dang
            # Và không trả về các thông tin như: (1 row affected)
            cursor.execute("SET XACT_ABORT ON; SET NOCOUNT ON;")
            yield cursor
            # Nếu thành công thì commit
            conn.commit()
        except Exception: # pylint: disable=broad-except
            # Nếu lỗi thì rollback dữ liệu
            if conn is not None:
                try:
                    conn.rollback()
                except Exception: # pylint: disable=broad-except
                    pass  # Không che lỗi gốc bằng lỗi rollback.
            raise
        finally:
            # Trả các connection về pool
            for resource in (cursor, conn):
                if resource is not None:
                    try:
                        resource.close()
                    except Exception: # pylint: disable=broad-except
                        pass

    @staticmethod
    def _read_sets(cursor):
        """
        MỘT STORE PROCEDURE CÓ THỂ TRẢ VỀ NHIỀU KẾT QUẢ  
        Hàm này đọc hết tất cả kết quả đó nhưng chỉ lấy kết quả mà có dữ liệu đầu tiên  
        Ví dụ:  
        ```
        Result 1:
        [("Quan",), ("Tra",)]

        Result 2:
        [(2,)]
        ```
        Thì chỉ trả về:  
        ```
        [
            ("Quan",),
            ("Tra",)
        ]
        ```
        """
        first = None
        while True:
            if cursor.description is not None:
                rows = [tuple(row) for row in cursor.fetchall()]
                if first is None:
                    first = rows
            if not cursor.nextset():
                break
        return [] if first is None else first

    @staticmethod
    def _failure(message = None):
        """
        Tạo id log và trả về id log cho người dùng, người dùng không cần biết chính xác lỗi  
        """
        # Chỉ log ID tương quan. Không logger.exception() vì traceback có thể chứa bí mật.
        error_id = uuid.uuid4().hex[:12]
        logger.error("Database gặp lỗi với error_id=%s, nội dung lỗi: %s", error_id, message)
        return {"success": False, "message": "Không thể xử lý cơ sở dữ liệu.",
                "data": None, "error_id": error_id}

    def _execute_query(self, query, params=None):
        """
        Hàm truy vấn dữ liệu như SELECT, INSERT, UPDATE, ...
        """
        try:
            # Mở một transaction và thực hiện
            with self._transaction() as cursor:
                if params is None:
                    cursor.execute(query)
                else:
                    cursor.execute(query, tuple(params))

                # Đọc kết quả
                rows = self._read_sets(cursor)
            return {"success": True, "message": "Thành công.", "data": rows}

        except Exception as e: # pylint: disable=broad-except
            return self._failure(str(e))

    def _check_connection(self):
        """
        Kiểm tra kết nối tới DB
        """
        return self._execute_query("SELECT 1")["success"]

    @staticmethod
    def _require_changed(result):
        """
        Dùng cho các câu truy vấn có OUTPUT inserted.XXX  
        Ví dụ:  
        ```
        UPDATE Users
        SET IsActive = 1
        OUTPUT inserted.Email
        WHERE Email = ?
        ```
        Thì kết quả trả về sẽ là email vừa được cập nhật, nếu `data = []` thì là không có dòng nào được cập nhật
        """
        if result["success"] and not result["data"]:
            result.update(success=False, message="Không tìm thấy tài khoản phù hợp.")
        return result

    def _check_user_exists(self, email):
        """
        Kiểm tra 1 user có tồn tại hay không  
        Nếu user tồn tại với email thì `[(1,)]` hoặc không tồn tại `[]`
        """
        result = self._execute_query("SELECT TOP (1) 1 FROM dbo.Users WHERE Email = ?", (email,))
        if not result["success"]:
            raise DatabaseError("Không kiểm tra được tài khoản")

        return bool(result["data"])

    def get_information_all_user(self):
        """
        Lấy thông tin toàn bộ nhân viên  
        Nên sử dụng phân trang khi mà số lượng lớn trên 1.000.000
        """
        return self._execute_query("SELECT UserName, Email, IsActive, ActivatedAt, Privilege FROM dbo.Users ORDER BY Email")

    def list_users(self, offset=0, limit=100):
        """
        Phân trang thông tin user
        """
        # Validation dữ liệu phân trang
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("offset >= 0, limit 1..500")

        return self._execute_query("""SELECT UserName, Email, IsActive, ActivatedAt, Privilege
            FROM dbo.Users ORDER BY Email OFFSET ? ROWS FETCH NEXT ? ROWS ONLY""", (offset, limit))

    def get_username(self, email):
        """
        Lấy tên người dùng thông qua email
        """
        return self._execute_query("SELECT UserName FROM dbo.Users WHERE Email = ?", (email,))

    def get_password_salt_password_privilege_user(self, email):
        """
        Lấy thông tin password để xác thực đăng nhập  
        Sau này nên cải tiến thành API Server
        """
        return self._execute_query("""SELECT PasswordHash, PasswordSalt, IsActive, ActivatedAt,
            Privilege FROM dbo.Users WHERE Email = ?""", (email,))

    def create_session_by_email(self, email, days=30, device_info=None):
        """
        Tạo session để ghi nhớ đăng nhập trong 30 ngày  
        Hàm này phải được gọi sau khi xác thực, có nghĩa là đã đăng nhập thành công  
        Vì hàm này không kiểm tra password nên phải xác thực trước mới gọi hàm này
        """
        # Validation email
        email = _text(email, "Email", 254)
        if type(days) is not int or not 1 <= days <= 30:
            raise ValueError("Thời gian ghi nhớ đăng nhập phải từ 1 đến 30")

        # Thiết bị đăng nhập
        if device_info is not None:
            device_info = _text(device_info, "Thiết bị", 256)

        # Tạo token đăng nhập
        token = secrets.token_urlsafe(32)
        try:
            with self._transaction() as cursor:
                # Đầu tiên lấy thông tin người đăng nhập
                cursor.execute("SELECT Email, IsActive FROM dbo.Users WITH (UPDLOCK, HOLDLOCK) WHERE Email = ?", (email,))

                # Xác thực thông tin người dùng có hợp lệ hay không
                users = self._read_sets(cursor)
                if len(users) != 1 or users[0][1] not in (True, 1):
                    return {"success": False, "message": "Tài khoản không hợp lệ.", "token": None}

                # Ghi thông tin token được mã hóa vào DB
                cursor.execute("""
                                INSERT dbo.AuthSessions(UserEmail, TokenHash, ExpiresAt, DeviceInfo)
                                OUTPUT inserted.SessionId, inserted.ExpiresAt
                                VALUES (?, ?, DATEADD(DAY, ?, SYSUTCDATETIME()), ?)
                            """, (users[0][0], _token_hash(token), days, device_info))

                # Lấy thông tin trả về
                row = self._read_sets(cursor)[0]
                expires = _utc(row[1]).isoformat()
            return {"success": True, "message": "Đã tạo phiên.", "token": token,
                    "session_id": row[0], "expires_at": expires}
        
        except Exception as e: # pylint: disable=broad-except
            result = self._failure(str(e))
            result["token"] = None
            return result

    def get_user_by_session(self, session_token):
        """
        hàm dùng để kiểm tra token mỗi lần người dùng mở app hoặc gọi API
        """
        # 1 token hợp lệ khi token_hash đúng, chưa Revoked, ExpiresAt lớn hơn hiện tại và User chưa bị khóa
        result = self._execute_query("""SELECT u.UserName, u.Email, u.IsActive,
            u.Privilege, CAST(1 AS bit) AS Status, s.ExpiresAt
            FROM dbo.AuthSessions AS s JOIN dbo.Users AS u ON u.Email = s.UserEmail
            WHERE s.TokenHash = ? AND s.RevokedAt IS NULL
              AND s.ExpiresAt > SYSUTCDATETIME() AND u.IsActive = 1""", (_token_hash(session_token),))

        # Lấy kết quả và xử lý thời gian hợp lệ
        if result["success"]:
            try:
                result["data"] = [row[:5] + (_utc(row[5]),) for row in result["data"]]
            except Exception as e: # pylint: disable=broad-except
                return self._failure(str(e))

        return result

    def revoke_session(self, session_token):
        """
        Thu hồi Session khi người dùng chủ động đăng xuất, hoặc quá trình tạo session lỗi
        """
        if not session_token:
            return {"success": True, "message": "Không có phiên cần thu hồi.", "data": []}

        # Cài đặt thời gian Revoked
        return self._execute_query("""UPDATE dbo.AuthSessions
            SET RevokedAt = SYSUTCDATETIME() WHERE TokenHash = ? AND RevokedAt IS NULL""",
            (_token_hash(session_token),))

    def revoke_all_sessions_by_email(self, email):
        """
        Thu hồi mọi phiên hiện có; khóa user cùng thứ tự với create_session.  
        Chức năng đăng xuất tất cả mọi thiết bị
        """
        # Validation email
        email = _text(email, "Email", 254)
        return self._execute_query("""
                                    DECLARE @e nvarchar(254);
                                    SELECT @e = Email FROM dbo.Users WITH (UPDLOCK,HOLDLOCK) WHERE Email = ?;
                                    UPDATE dbo.AuthSessions SET RevokedAt = SYSUTCDATETIME()
                                    WHERE UserEmail = @e AND RevokedAt IS NULL;
                                    """, (email,))

    def revoke_session_by_id(self, session_id, email):
        """
        Thu hồi một thiết bị;  
        API phải lấy email từ phiên caller, không từ form tùy ý.
        """
        # Validation session id
        if type(session_id) is not int or session_id < 1:
            raise ValueError("Session ID phải là số nguyên dương")

        # Cập nhật thời gian revoked theo session id và email để tránh người A revoked session người B
        return self._execute_query("""UPDATE dbo.AuthSessions SET RevokedAt = SYSUTCDATETIME()
            WHERE SessionId = ? AND UserEmail = ? AND RevokedAt IS NULL""", (session_id, email))

    def list_sessions_by_email(self, email, limit=100):
        """
        Lấy danh sách session đăng nhập còn tác dụng của 1 tài khoản  
        Ví dụ:  
        ```
        Thiết bị của bạn
        125 | Quan Laptop    | 14/09 | 14/10
        122 | Office Desktop | 10/09 | 10/10
        118 | Home PC        | 01/09 | 01/10
        ```
        """
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("limit phải từ 1 đến 500")

        return self._execute_query("""SELECT TOP (?) SessionId, DeviceInfo, CreatedAt, ExpiresAt
            FROM dbo.AuthSessions WHERE UserEmail = ? AND RevokedAt IS NULL
            AND ExpiresAt > SYSUTCDATETIME() ORDER BY SessionId DESC""", (limit, email))

    def cleanup_expired_sessions(self, batch_size=1000, retention_days=30):
        """
        Session hết hạn/revoke không nên để vô hạn trong DB.  
        Tiến hành xóa các session quá cũ theo từng batch  
        Chỉ xóa các session hết hạn quá retention day
        """
        if type(batch_size) is not int or not 1 <= batch_size <= 10000:
            raise ValueError("batch_size phải từ 1 đến 10000")

        if type(retention_days) is not int or not 1 <= retention_days <= 365:
            raise ValueError("retention_days phải từ 1 đến 365")
        
        return self._execute_query("""DELETE TOP (?) FROM dbo.AuthSessions
            OUTPUT deleted.SessionId
            WHERE ExpiresAt < DATEADD(DAY, -?, SYSUTCDATETIME())
               OR RevokedAt < DATEADD(DAY, -?, SYSUTCDATETIME())""",
            (batch_size, retention_days, retention_days))

    def _change_user_and_revoke(self, email, assignment, values, *, delete=False):
        """
        Một transaction: Thay đổi thông tin bảo mật của user + vô hiệu hóa session  
        Vì `"UPDATE dbo.Users SET " + assignment` nên để đảm bảo không bị SQL Injection thì chỉ sử dụng hàm này trong nội bộ  
        Không cho phép người dùng truyền vào assignment
        """
        try:
            with self._transaction() as cursor:
                # Khóa user để bắt đầu thao tác
                cursor.execute("SELECT Email FROM dbo.Users WITH (UPDLOCK,HOLDLOCK) WHERE Email = ?", (email,))

                rows = self._read_sets(cursor)
                if len(rows) != 1:
                    return {"success": False, "message": "Không tìm thấy tài khoản duy nhất.", "data": []}

                # Delete user cần xóa session con trước vì có foreign key.
                statement = ("DELETE FROM dbo.AuthSessions WHERE UserEmail = ?" if delete else
                    "UPDATE dbo.AuthSessions SET RevokedAt=SYSUTCDATETIME() WHERE UserEmail=? AND RevokedAt IS NULL")

                cursor.execute(statement, (email,))
                self._read_sets(cursor)

                # Xóa thông tin ngươi dùng
                query = ("DELETE FROM dbo.Users OUTPUT deleted.Email WHERE Email = ?" if delete else
                         "UPDATE dbo.Users SET " + assignment + " OUTPUT inserted.Email WHERE Email = ?")

                cursor.execute(query, tuple(values) + (email,))
                changed = self._read_sets(cursor)

            return {"success": True, "message": "Đã cập nhật và vô hiệu phiên cũ.", "data": changed}
        except Exception as e: # pylint: disable=broad-except
            return self._failure(str(e))

    def activate_user(self, email, activate=True):
        """
        Kích hoạt hoặc khóa tài khoản người dùng
        """
        if type(activate) is not bool:
            raise ValueError("activate phải là bool")

        # Tiến hành khóa tài khoản người dùng và hủy các session đang còn hạn
        if not activate:
            return self._change_user_and_revoke(email, "IsActive=0", ())

        # Giữ GETDATE cho ActivatedAt legacy; không đổi ngầm quy ước thời gian cũ.
        return self._require_changed(self._execute_query("""
                                                            UPDATE dbo.Users
                                                            SET IsActive=1, 
                                                            ActivatedAt=GETDATE() 
                                                            OUTPUT inserted.Email
                                                            WHERE Email=?
                                                        """, (email,)))

    def create_new_user(self, username, email, password, privilege="User"):
        """
        Tạo người dùng mới
        """
        # Validation thông tin đầu vào
        username = _text(username, "Tên", 200)
        email = _text(email, "Email", 254)
        password = _text(password, "Mật khẩu", 1024, strip=False)
        privilege = _text(privilege, "Quyền", 100)
        salt, hashed = Hash.scrypt(password=password)

        # Thêm thông tin người dùng vào DB
        return self._require_changed(self._execute_query("""
                                                            INSERT dbo.Users
                                                            (UserName, Email, PasswordHash, PasswordSalt, Privilege)
                                                            OUTPUT inserted.Email VALUES (?,?,?,?,?)
                                                        """,(username,email,hashed,salt,privilege)))

    def update_password_user(self, email, password=None):
        """
        Cập nhật mật khẩu của người dùng
        """
        password = _text(password, "Mật khẩu", 1024, strip=False)
        salt, hashed = Hash.scrypt(password=password)

        # Cập nhật mật khẩu mới và đăng xuất các session
        return self._change_user_and_revoke(email,
            "PasswordHash=?, PasswordSalt=?, OTP=NULL, Expired_OTP=NULL", (hashed,salt))

    def change_role_user(self, privilege, email):
        """
        Thay đổi quyền hạn người dùng và tiến hành hủy các session còn hạn
        """
        return self._change_user_and_revoke(email, "Privilege=?", (_text(privilege,"Quyền",100),))

    def delete_account(self, email):
        """
        Xóa tài khoản thật, chỉ quản trị viên. FK khác có thể chặn -> rollback cả session.
        Thường dùng activate_user(email, False) để giữ lịch sử thay cho xóa.
        """
        return self._change_user_and_revoke(email, "", (), delete=True)

    def get_otp_and_expired_time(self, email, purpose="reset_password"):
        """
        Lấy OTP và thời gian hết hạn theo email + mục đích sử dụng OTP.

        Ví dụ purpose:
            - reset_password
            - verify_email
            - change_password
        """
        if not self.allow_legacy_otp:
            raise DatabaseError(
                "OTP legacy đã tắt; sử dụng account_service ở server"
            )

        email = _text(email, "Email", 254)
        purpose = _text(purpose, "Purpose", 100)

        return self._execute_query(
            """
            SELECT TOP (1)
                OTP,
                Expired_OTP,
                Purpose,
                CreatedAt
            FROM dbo.UserOTP
            WHERE Email = ?
            AND Purpose = ?
            ORDER BY CreatedAt DESC
            """,
            (email, purpose)
        )


    def update_otp_and_time_expired(self, email, otp, time_expired, purpose="reset_password"):
        """
        Tạo mới hoặc cập nhật OTP.

        - Nếu Email + Purpose chưa có OTP:
            -> INSERT một bản ghi mới vào UserOTP.

        - Nếu Email + Purpose đã có:
            -> UPDATE OTP, thời gian hết hạn và CreatedAt.

        UserId được lấy từ bảng Users theo Email.
        """
        if not self.allow_legacy_otp:
            raise DatabaseError(
                "OTP legacy đã tắt; sử dụng account_service ở server"
            )

        email = _text(email, "Email", 254)
        OTP = _text(otp, "OTP", 50, strip=False)
        purpose = _text(purpose, "Purpose", 100)

        result = self._execute_query(
            """
            DECLARE @UserId INT;

            -- Lấy UserId của tài khoản
            SELECT @UserId = UserId
            FROM dbo.Users WITH (UPDLOCK, HOLDLOCK)
            WHERE Email = ?;

            -- Chỉ xử lý khi tài khoản tồn tại
            IF @UserId IS NOT NULL
            BEGIN

                -- Khóa bản ghi OTP tương ứng để tránh 2 request
                -- cùng lúc cùng tạo OTP.
                IF EXISTS
                (
                    SELECT 1
                    FROM dbo.UserOTP WITH (UPDLOCK, HOLDLOCK)
                    WHERE Email = ?
                    AND Purpose = ?
                )
                BEGIN
                    -- Đã có OTP -> cập nhật
                    UPDATE dbo.UserOTP
                    SET
                        OTP = ?,
                        Expired_OTP = ?,
                        CreatedAt = SYSUTCDATETIME()
                    WHERE Email = ?
                    AND Purpose = ?;
                END
                ELSE
                BEGIN
                    -- Chưa có OTP -> thêm mới
                    INSERT INTO dbo.UserOTP
                    (
                        UserId,
                        Email,
                        OTP,
                        Expired_OTP,
                        Purpose,
                        CreatedAt
                    )
                    VALUES
                    (
                        @UserId,
                        ?,
                        ?,
                        ?,
                        ?,
                        SYSUTCDATETIME()
                    );
                END

                -- Trả kết quả về Python
                SELECT TOP (1)
                    UserId,
                    Email,
                    OTP,
                    Expired_OTP,
                    Purpose,
                    CreatedAt
                FROM dbo.UserOTP
                WHERE Email = ?
                AND Purpose = ?;
            END
            """,
            (
                email,                  # SELECT Users
                email, purpose,         # EXISTS
                OTP, time_expired,      # UPDATE SET
                email, purpose,         # UPDATE WHERE
                email,                  # INSERT Email
                OTP,                    # INSERT OTP
                time_expired,           # INSERT Expired_OTP
                purpose,                # INSERT Purpose
                email, purpose          # SELECT kết quả
            )
        )

        return self._require_changed(result)

    def resolve_or_register_external_user(self, provider, provider_user_id, provider_email, display_name):
        """
        Khi người dùng đăng nhập bằng Google/Facebook  
        Kiểm tra xem đã có tài khoản nội bộ chưa
        Chưa có thì tạo mới, có rồi mà chưa liên kết tài khoản nội bộ với tài khoản GG/FB thì thông báo

        Kết quả:
            LOGIN_ALLOWED
            ACCOUNT_INACTIVE
            LINK_REQUIRED
            CREATED_PENDING
        """

        if provider not in {"google", "facebook"}:
            raise ValueError("Provider không hỗ trợ")

        if (not isinstance(provider_user_id, str) or not provider_user_id.strip() or len(provider_user_id) > 255):
            raise ValueError("Provider ID không hợp lệ")

        if (not isinstance(provider_email, str) or not provider_email.strip() or len(provider_email) > 320):
            raise ValueError("Email provider không hợp lệ")

        if not isinstance(display_name, str) or not display_name.strip():
            display_name = "Người dùng mới"

        # Giới hạn tên hiển thị; không cắt email hoặc provider ID.
        display_name = display_name.strip()[:200]

        query = """
            EXEC dbo.usp_ResolveOrRegisterExternalUser
                @Provider = ?,
                @ProviderUserId = ?,
                @ProviderEmail = ?,
                @DisplayName = ?
        """
        params = (provider, provider_user_id, provider_email.strip(), display_name)

        return self._execute_query(query, params)

    def link_google_account(self, user_email: str, google_id: str, google_email: str | None):
        """
        Liên kết Google với tài khoản nội bộ đã đăng nhập.

        user_email:
            Email nội bộ lấy từ phiên đăng nhập hiện tại.

        google_id:
            Trường 'sub' do Google trả về.

        google_email:
            Email Google, chỉ là thông tin bổ sung.
        """
        if not isinstance(user_email, str) or not user_email.strip():
            raise ValueError("Thiếu tài khoản nội bộ.")

        user_email = user_email.strip()

        if len(user_email) > 320:
            raise ValueError("Email nội bộ quá dài.")

        if (not isinstance(google_id, str) or not google_id.strip() or len(google_id) > 255):
            raise ValueError("Định danh Google không hợp lệ.")

        if google_email is not None:
            if not isinstance(google_email, str):
                raise ValueError("Email Google không hợp lệ.")

            google_email = google_email.strip() or None

            if google_email is not None and len(google_email) > 320:
                raise ValueError("Email Google quá dài.")

        query = """
                    EXEC dbo.usp_LinkExternalLoginIfNotExists
                @UserEmail = ?,
                @Provider = ?,
                @ProviderUserId = ?,
                @ProviderEmail = ?
        """
        params = (user_email, "google", google_id, google_email)

        return self._execute_query(query, params)

    def update_last_login_at(self, email):
        """
        Cập nhật thời gian đăng nhập
        """
        return self._execute_query("EXEC dbo.usp_UpdateLastLoginAt @Email=?", (email,))
