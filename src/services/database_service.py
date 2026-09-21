"""
Lớp truy cập SQL Server cho Users / UserProfiles / UserExternalLogin.
"""
from __future__ import annotations
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import hmac
import logging
import os
import re
import secrets
import uuid
import pyodbc

# Mở comment 3 dòng bên dưới mỗi khi test (Chạy trực tiếp hàm if __main__)
# import os,sys
# PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# sys.path.append(PROJECT_DIR)
from services.hash import Hash
from utils.utils import get_odbc_drivers_for_sql_server


# Bật cơ chế tái sử dụng kết nối của ODBC.
# Theo tài liệu Microsoft, việc bật pooling sẽ giúp cải thiện hiệu suất khi làm việc với ODBC.
# Và phải thiết lập pyodbc.pooling phải được thực hiện trước kết nối đầu tiên của tiến trình
pyodbc.pooling = True

# Thiết lập logger cho database_service
logger = logging.getLogger(__name__)
UNSET = object()  # Phân biệt: bỏ qua trường với chủ ý gán NULL.


class DatabaseError(RuntimeError):
    """Lỗi cấu hình/dữ liệu; không chứa SQL hay thông tin kết nối."""


# Danh sách cố định: tên procedure/cột KHÔNG lấy từ dữ liệu người dùng.
PROCEDURES = {
    'get'       : ('usp_User_Get', ('UserId', 'Email')),
    'list'      : ('usp_User_List', ('UserId', 'Email', 'PageNumber', 'PageSize')),
    'register'  : ('usp_User_RegisterLocal', ('Email', 'UserName', 'PasswordHash', 'PasswordSalt',
                'FullName', 'PhoneNumber', 'DateOfBirth', 'Address', 'AvatarUrl')),
    'external'  : ('usp_User_LoginExternal', ('Provider', 'ProviderUserId', 'AccountEmail',
                'ProviderEmail', 'UserName', 'FullName', 'PhoneNumber', 'DateOfBirth', 'Address', 'AvatarUrl')),
    'profile'   : ('usp_User_UpdateProfile', ('UserId', 'Email', 'UserName', 'FullName',
                'SetFullName', 'PhoneNumber', 'SetPhoneNumber', 'DateOfBirth', 'SetDateOfBirth',
                'Address', 'SetAddress', 'AvatarUrl', 'SetAvatarUrl')),
    'delete'    : ('usp_User_Delete', ('UserId', 'Email')),
    'link'      : ('usp_User_LinkExternal', ('UserId', 'Provider', 'ProviderUserId', 'ProviderEmail')),
    'unlink'    : ('usp_User_UnlinkExternal', ('UserId', 'Provider', 'ProviderUserId')),
    'activate'  : ('usp_User_Activate', ('UserId', 'Email')),
    'deactivate': ('usp_User_Deactivate', ('UserId', 'Email')),
    'status'    : ('usp_User_SetStatus', ('Status', 'UserId', 'Email')),
    'email'     : ('usp_User_ChangeEmail', ('NewEmail', 'UserId', 'Email')),
    'credentials': ('usp_User_GetLocalCredentials', ('Email',)),
    'login'     : ('usp_User_RecordLocalLogin', ('UserId', 'ExpectedAuthVersion')),
    'password'  : ('usp_User_SetPassword', ('UserId', 'PasswordHash', 'ExpectedAuthVersion', 'PasswordSalt')),
}

# Chỉ đưa thông báo đã định nghĩa ra ngoài, không trả nguyên lỗi ODBC.
ERRORS = {
    51100: ('NOT_FOUND', 'Không tìm thấy tài khoản.'),
    51101: ('INVALID_PAGE', 'Thông tin phân trang không hợp lệ.'),
    51102: ('TRANSACTION_MODE', 'Cấu hình transaction chưa phù hợp.'),
    51103: ('BUSY', 'Hệ thống đang bận; vui lòng thử lại.'),
    51104: ('ACCOUNT_INACTIVE', 'Tài khoản chưa kích hoạt hoặc đã bị vô hiệu hóa.'),
    51105: ('INVALID_EMAIL', 'Email không hợp lệ.'),
    51106: ('EMAIL_EXISTS', 'Email đã có tài khoản.'),
    51107: ('MISSING_DATA', 'Thiếu thông tin đăng ký bắt buộc.'),
    51108: ('INVALID_DOB', 'Ngày sinh không được ở tương lai.'),
    51109: ('INVALID_PROVIDER', 'Thông tin tài khoản bên ngoài không hợp lệ.'),
    51110: ('INVALID_NAME', 'Tên hiển thị không được rỗng.'),
    51111: ('EXTERNAL_IN_USE', 'Tài khoản bên ngoài đã thuộc người khác.'),
    51112: ('LINK_NOT_FOUND', 'Không tìm thấy liên kết.'),
    51113: ('LAST_LOGIN_METHOD', 'Không thể xóa phương thức đăng nhập cuối cùng.'),
    51115: ('AUTH_CHANGED', 'Thông tin xác thực đã thay đổi; hãy xác thực lại.'),
    51116: ('INVALID_HASH', 'Hash mật khẩu không hợp lệ.'),
    51117: ('AMBIGUOUS_EMAIL', 'Email khớp nhiều tài khoản; cần kiểm tra dữ liệu.'),
    2601: ('DUPLICATE', 'Dữ liệu đã tồn tại.'),
    2627: ('DUPLICATE', 'Dữ liệu đã tồn tại.'),
    547: ('RELATED_DATA', 'Dữ liệu liên quan không cho phép thao tác này.'),
    208: ('MISSING_SCHEMA', 'Thiếu bảng; kiểm tra script cài đặt.'),
    2812: ('MISSING_PROCEDURE', 'Chưa cài đủ procedure cần thiết.'),
    51300: ('INVALID_OTP_EXPIRY', 'Hạn OTP phải ở tương lai và không quá 15 phút.'),
    1205: ('BUSY', 'Giao dịch bị xung đột; vui lòng thử lại.'),
}

def _text(value, name, maximum, *, strip=True):
    """
    Check chuỗi text không rỗng, không chứa null, và không vượt quá giới hạn UTF-16 code units.
    """
    if not isinstance(value, str):
        raise ValueError(f'{name} phải là chuỗi')

    value = value.strip() if strip else value

    # NVARCHAR(n) tính theo UTF-16 code units; emoji có thể chiếm hai đơn vị.
    if not value or '\x00' in value or len(value.encode('utf-16-le')) // 2 > maximum:
        raise ValueError(f'{name} rỗng hoặc vượt giới hạn {maximum}')
    return value


def _optional(value, name, maximum):
    """
    Check chuỗi text có thể rỗng hoặc None, nhưng nếu có giá trị thì phải hợp lệ.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _text(value, name, maximum)


def _email(value, *, optional=False):
    """
    Check email cơ bản, không thay thế xác minh quyền sở hữu email ở backend.
    """
    if optional and (value is None or value == ''):
        return None

    value = _text(value, 'Email', 320).lower()
    # Kiểm tra cơ bản; không thay thế xác minh quyền sở hữu email ở backend.
    if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
        raise ValueError('Email không hợp lệ')
    return value

def _user_id(value):
    """
    Check UserId là chuỗi ASCII tối đa 16 ký tự, hoặc None.
    """
    if value is None or value == '':
        return None

    value = _text(value, 'UserId', 16)
    if not value.isascii():
        raise ValueError('UserId phải là chuỗi ASCII tối đa 16 ký tự')
    return value


def _who(user_id=None, email=None, *, allow_empty=False):
    """
    Trả về (user_id, email) đã chuẩn hóa.
    - Nếu user_id hợp lệ thì ưu tiên dùng user_id, bỏ qua email.
    - Nếu user_id không hợp lệ thì dùng email.
    - Nếu cả hai đều không hợp lệ và allow_empty=False thì raise ValueError.

    Hai giá trị này dùng để gọi procedure, không dùng trực tiếp trong SQL.
    """
    uid = _user_id(user_id)
    # ID ưu tiên: bỏ qua email kể cả email không hợp lệ, đúng hợp đồng SQL.
    address = None if uid else _email(email, optional=True)
    if not uid and not address and not allow_empty:
        raise ValueError('Phải truyền UserId hoặc email')

    return uid, address


def _positive(value, name, maximum=None):
    """
    Check số nguyên dương, có thể giới hạn tối đa.
    """
    if type(value) is not int or value < 1 or (maximum is not None and value > maximum):
        raise ValueError(f'{name} phải là số nguyên dương trong giới hạn cho phép')
    return value


def _dob(value):
    """
    Check ngày sinh là date, không ở tương lai.
    """
    if value is None:
        return None

    if isinstance(value, str):
        value = date.fromisoformat(value)

    if isinstance(value, datetime) or not isinstance(value, date):
        raise ValueError('Ngày sinh phải là date hoặc YYYY-MM-DD')

    if value > datetime.now(timezone.utc).date():
        raise ValueError('Ngày sinh không được ở tương lai')
    return value


def _utc(value):
    """
    Check datetime là UTC, nếu không có timezone thì gán UTC, nếu có timezone thì convert sang UTC.
    """
    if not isinstance(value, datetime):
        logger.error('Thời gian database trả về không hợp lệ (kiểu %s): %s', type(value), value)
        raise DatabaseError('Thời gian database trả về không hợp lệ')
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _token_hash(token):
    """
    Hash SHA-256 cho token ngẫu nhiên, không dùng cho mật khẩu/OTP.
    """
    # SHA-256 chỉ dùng cho TOKEN NGẪU NHIÊN entropy cao, không dùng cho password/OTP.
    return hashlib.sha256(_text(token, 'Token', 8192, strip=False).encode()).digest()


def _odbc_value(value):
    """
    Bao giá trị trong {} và escape dấu } để mật khẩu chứa ; không phá connection string.
    """
    # Bao giá trị trong {} và escape dấu } để mật khẩu chứa ; không phá connection string.
    value = str(value)
    if '\x00' in value:
        logger.error('Giá trị kết nối không hợp lệ: %s', value)
        raise ValueError('Giá trị kết nối không hợp lệ')
    return '{' + value.replace('}', '}}') + '}'

def _error(code, message):
    """
    Trả về dict lỗi chuẩn, không log chi tiết.
    """
    return {'success': False, 'code': code, 'message': message, 'data': [],
            'columns': [], 'records': [], 'result_sets': []}

class MyDatabase:
    """
    Lớp quản lý kết nối đến cơ sở dữ liệu SQL Server.
    """
    def __init__(self, server_name='localhost', database_name="DucQuanApp", user_name="ducquan_user", password="123456789",
                 *, connect_timeout=5, query_timeout=15, trust_server_certificate=True):
        """
        Khởi tạo kết nối đến cơ sở dữ liệu SQL Server.
        """
        # Các tham số kết nối tới SQL Server, có thể lấy từ biến môi trường nếu không truyền trực tiếp.
        self.database_name = database_name
        self._connect_timeout = _positive(connect_timeout, 'Connect timeout')
        self._query_timeout = _positive(query_timeout, 'Query timeout')
        drivers = get_odbc_drivers_for_sql_server()
        if not drivers:
            raise DatabaseError('Chưa cài ODBC Driver for SQL Server')
        driver = drivers[-1]
        user_name = user_name if user_name is not None else os.getenv('DB_USER')
        password = password if password is not None else os.getenv('DB_PASSWORD')

        # Kiểm tra thông tin đăng nhập
        if user_name:
            if password is None:
                raise DatabaseError('Thiếu mật khẩu SQL Server')
            auth = f'UID={_odbc_value(user_name)};PWD={_odbc_value(password)};'
        else:
            if password is not None:
                raise DatabaseError('Có mật khẩu nhưng thiếu tên đăng nhập SQL Server')
            auth = 'Trusted_Connection=yes;'

        # Tạo chuỗi kết nối ODBC cho SQL Server
        self._connection_string = (
            f'DRIVER={_odbc_value(driver)};'
            f'SERVER={_odbc_value(server_name)};'
            f'DATABASE={_odbc_value(database_name)};'
            f'{auth}Encrypt=yes;'
            f'TrustServerCertificate={"yes" if trust_server_certificate else "no"};'
        )

    def _connect(self, *, autocommit=True):
        """
        Kết nối đến cơ sở dữ liệu SQL Server với các tham số đã thiết lập.
        """
        conn = pyodbc.connect(self._connection_string, timeout=self._connect_timeout,
                               autocommit=autocommit)
        try:
            conn.timeout = self._query_timeout
            return conn
        except Exception as e: # pylint: disable=broad-except
            logger.error('Lỗi khi kết nối đến cơ sở dữ liệu: %s', str(e))
            conn.close()
            raise

    @staticmethod
    def _close(resource):
        """
        Đóng tài nguyên (cursor hoặc connection) nếu không phải None.
        """
        if resource is not None:
            try:
                resource.close()
            except Exception as e: # pylint: disable=broad-except
                logger.error('Lỗi khi đóng tài nguyên (cursor): %s', str(e))

    @contextmanager
    def _cursor(self, *, transactional=False):
        """
        Cung cấp một cursor để thực hiện các truy vấn SQL. Nếu transactional=True, sẽ bắt đầu một transaction và commit/rollback khi kết thúc.
        """
        conn = cursor = None
        try:
            # Tạo kết nối đến cơ sở dữ liệu với autocommit=False nếu transactional=True, ngược lại autocommit=True.
            conn = self._connect(autocommit=not transactional)
            cursor = conn.cursor()

            # Nếu là transactional, bật XACT_ABORT và NOCOUNT để đảm bảo transaction được rollback khi có lỗi.
            # Sau đó bắt đầu transaction nếu chưa có transaction nào đang mở ở connection này.
            if transactional:
                cursor.execute('SET XACT_ABORT ON; SET NOCOUNT ON; IF @@TRANCOUNT=0 BEGIN TRANSACTION;')
            yield cursor

            # Nếu là transactional, commit transaction khi không có lỗi.
            if transactional:
                conn.commit()
        except Exception as e: # pylint: disable=broad-except
            logger.error('Lỗi khi thực hiện transaction: %s', str(e))
            if conn is not None and transactional:
                try:
                    conn.rollback()
                except Exception as exc: # pylint: disable=broad-except
                    logger.error('Lỗi khi rollback transaction: %s', str(exc))
            raise

        finally:
            self._close(cursor)
            self._close(conn)

    def _transaction(self):
        """Chỉ dành cho SQL phụ. TUYỆT ĐỐI không gọi usp_User_* bên trong."""
        return self._cursor(transactional=True)

    @staticmethod
    def _read_sets(cursor):
        """Đọc HẾT result set, kể cả set rỗng có metadata.

        Đọc nextset đến cuối còn giúp nhận lỗi muộn từ SQL Server trước khi
        báo thành công. Mỗi set giữ tên cột và tuple để caller tự chọn cách đọc.
        """
        sets = []
        while True:
            # Nếu cursor.description là None, tức là không có result set (ví dụ UPDATE/INSERT), thì bỏ qua và tiếp tục nextset.
            if cursor.description is not None:
                # Lấy tên cột và dữ liệu từ result set hiện tại.
                columns = [item[0] for item in cursor.description]
                rows = [tuple(row) for row in cursor.fetchall()]
                sets.append({'columns': columns, 'data': rows,
                             'records': [dict(zip(columns, row)) for row in rows]})

            # Nếu không còn result set nào nữa, thoát vòng lặp. Nếu còn result set, tiếp tục đọc.
            if not cursor.nextset():
                break
        return sets

    @staticmethod
    def _success(sets=None, message='Thành công.'):
        """
        Xây dựng dict kết quả thành công chuẩn, có thể có nhiều result set. Nếu sets là None, trả về dict mặc định với dữ liệu rỗng.
        """
        sets = [] if sets is None else sets
        # Nếu có ít nhất một result set, lấy result set đầu tiên để trả về dữ liệu chính. Nếu không có result set nào, trả về dict mặc định với dữ liệu rỗng.
        first = sets[0] if sets else {'columns': [], 'data': [], 'records': []}
        return {'success': True, 'code': 'OK', 'message': message,
                'data': first['data'], 'columns': first['columns'],
                'records': first['records'], 'result_sets': sets}

    @staticmethod
    def _failure(exc=None):
        """
        Xây dựng dict kết quả thất bại chuẩn, không log chi tiết.  
        Nếu exc là pyodbc.Error, lấy mã lỗi native để phân loại.
        Nếu exc là Exception khác, trả về lỗi DATABASE_ERROR.
        """
        # Không log str(exc): ODBC có thể chứa SQL, PII hoặc tham số nhạy cảm.
        error_id = uuid.uuid4().hex[:12]
        native = None

        # Nếu exc là pyodbc.Error, lấy mã lỗi native trong dấu ngoặc của diagnostic ODBC. Nếu không, native sẽ là None.
        if isinstance(exc, pyodbc.Error):
            # Chỉ nhận mã lỗi native trong dấu ngoặc của diagnostic ODBC.
            codes = [int(n) for n in re.findall(r'\((\d{3,5})\)', str(exc))]
            native = next((n for n in codes if n in ERRORS), None)

        # Lấy code và message từ ERRORS nếu native có trong danh sách, nếu không thì trả về DATABASE_ERROR.
        code, message = ERRORS.get(native, ('DATABASE_ERROR', 'Không thể xử lý cơ sở dữ liệu.'))
        logger.error('Database error id=%s category=%s', error_id, code)
        logger.error('Database error id=%s message=%s', error_id, message)
        result = _error(code, message)
        result['error_id'] = error_id
        return result

    def _execute_query(self, query, params=None, *, transactional=True):
        """
        Thực thi một truy vấn SQL với các tham số đã cho. Trả về dict kết quả chuẩn.  
        Nếu transactional=True, sẽ thực hiện trong transaction và rollback khi có lỗi.
        """
        try:
            with self._cursor(transactional=transactional) as cursor:
                cursor.execute(query, tuple(params or ()))
                sets = self._read_sets(cursor)

            return self._success(sets)

        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi thực thi truy vấn SQL: %s', str(exc))
            return self._failure(exc)

    def _call(self, action, *values):
        """
        Gọi một stored procedure đã được whitelist trong PROCEDURES với các giá trị đã cho.
        """
        name, parameters = PROCEDURES[action]  # Whitelist cố định ở đầu file.
        if len(values) != len(parameters):
            raise ValueError('Số tham số gọi procedure không trùng khớp với số tham số định nghĩa')

        # Tạo chuỗi assignments cho các tham số, ví dụ: @param1=?, @param2=?, ...
        assignments = ', '.join(f'@{parameter}=?' for parameter in parameters)
        # Khi gọi procedure thì thiết lập transactional=False để không bắt transaction trong procedure, vì procedure có thể tự quản lý transaction.
        return self._execute_query(f'EXEC dbo.{name} {assignments}', values, transactional=False)

    def _check_connection(self):
        """
        Kiểm tra kết nối đến cơ sở dữ liệu bằng cách thực hiện một truy vấn đơn giản.
        """
        return self._execute_query('SELECT 1', transactional=False)['success']

    @staticmethod
    def _require_changed(result):
        """
        Kiểm tra kết quả trả về từ procedure có thay đổi dữ liệu hay không.  
        Dùng cho các procedure UPDATE/DELETE.  
        Nếu không có thay đổi, trả về lỗi NOT_FOUND. Nếu có thay đổi, trả về kết quả gốc.
        """
        if result['success'] and not result['data']:
            return _error('NOT_FOUND', 'Không tìm thấy tài khoản phù hợp.')
        return result

    def _check_user_exists(self, email):
        """
        Kiểm tra xem người dùng có tồn tại không.
        """
        result = self.get_user(email=email)
        if result['success']:
            return True
        if result['code'] == 'NOT_FOUND':
            return False
        raise DatabaseError('Không kiểm tra được tài khoản')

    def get_user(self, email=None, *, user_id=None):
        """
        Lấy thông tin người dùng theo email hoặc ID.
        Trả thêm user=dict và external_logins=list[dict].
        """
        # Gọi stored procedure 'usp_User_Get' với user_id và email đã chuẩn hóa.
        result = self._call('get', *_who(user_id, email))

        # Nếu có kết quả, lấy user từ result_sets đầu tiên
        result['user'] = result['records'][0] if result['success'] and result['records'] else None
        # external_logins từ result_sets thứ hai (nếu có).
        result['external_logins'] = result['result_sets'][1]['records'] if len(result['result_sets']) > 1 else []

        # Nếu không có kết quả, trả về user=None và external_logins=[].
        return result

    def list_users_page(self, page_number=1, page_size=20, *, user_id=None, email=None):
        """
        Lấy danh sách người dùng theo trang, với phân trang bằng page_number và page_size.
        Trả về total_rows, users=list[dict].
        """
        # Kiểm tra page_number và page_size là số nguyên dương, nếu không hợp lệ thì trả về lỗi INVALID_INPUT.
        page_number = _positive(page_number, 'Trang', 2147483647)
        page_size = _positive(page_size, 'Số dòng', 200)
        if page_number is None or page_size is None:
            return _error('INVALID_INPUT', 'Tham số trang và số dòng không hợp lệ.')

        # Gọi stored procedure 'usp_User_List' với user_id, email, page_number và page_size đã chuẩn hóa.
        result = self._call('list', *_who(user_id, email, allow_empty=True), page_number, page_size)

        # Nếu có kết quả, lấy tổng số dòng từ result_sets đầu tiên và danh sách người dùng từ result_sets thứ hai (nếu có).
        result['total_rows'] = result['records'][0]['TotalRows'] if result['success'] and result['records'] else 0
        result['users'] = result['result_sets'][1]['records'] if len(result['result_sets']) > 1 else []

        # Nếu không có kết quả, trả về total_rows=0 và users=[].
        return result

    def list_users(self, offset=0, limit=100):
        """
        Lấy danh sách người dùng với phân trang bằng offset và limit.  
        - offset: số dòng bỏ qua, phải là số nguyên >=0.
        - limit: số dòng tối đa trả về, phải là số nguyên dương <=200.

        Vì khi offset lớn, việc gọi list_users_page nhiều lần có thể gây tốn tài nguyên, nên hàm này chỉ nên dùng cho các trường hợp cần lấy một số lượng nhỏ người dùng.
        """
        # Kiểm tra offset là số nguyên >=0, nếu không hợp lệ thì raise ValueError.
        if type(offset) is not int or offset < 0:
            raise ValueError('offset phải là số nguyên >=0')

        # Kiểm tra limit là số nguyên dương <=200, nếu không hợp lệ thì raise ValueError.
        limit = _positive(limit, 'limit', 200)
        # Tính toán page và skip dựa trên offset và limit. (page là số trang, skip là số dòng bỏ qua trong trang đó)
        page, skip = divmod(offset, limit) # divmod trả về (offset // limit, offset % limit)

        # Gọi list_users_page để lấy trang đầu tiên
        result = self.list_users_page(page + 1, limit)

        if not result['success']:
            return result

        # Lấy các dòng từ skip đến hết trang.
        # Ví dụ: nếu offset=5, limit=10, thì page=0, skip=5, sẽ lấy từ dòng 5 đến dòng 9 (tổng cộng 5 dòng) từ trang đầu tiên.
        rows = result['users'][skip:]

        # Nếu số dòng lấy được ít hơn limit và vẫn còn dòng tiếp theo, thì gọi list_users_page để lấy trang tiếp theo và nối vào rows.
        # ví dụ: nếu offset=5, limit=10, và trang đầu tiên chỉ có 5 dòng, thì sẽ lấy thêm 5 dòng từ trang tiếp theo để đủ 10 dòng.
        if skip and len(rows) < limit and offset + len(rows) < result['total_rows']:
            following = self.list_users_page(page + 2, limit)
            if not following['success']:
                return following
            rows += following['users'][:limit-len(rows)]

        # Chỉ định các cột cố định để trả về, và chuẩn hóa dữ liệu thành dạng tuple cho data.
        columns = ['UserName', 'Email', 'IsActivate', 'ActivatedAt', 'Privilege']
        data = [tuple(row[c] for c in columns) for row in rows]

        # Cập nhật lại kết quả các trường users, records, columns và data để trả về kết quả đầy đủ.
        result.update(users=rows, records=rows, columns=columns, data=data)
        return result

    def get_information_all_user(self):
        """
        Lấy thông tin tất cả người dùng, không phân trang.
        """
        # Khai báo danh sách all_rows để lưu trữ tất cả người dùng và biến page để phân trang.
        all_rows, page = [], 1

        # Chạy vòng lặp để gọi list_users_page cho đến khi không còn người dùng nào nữa. Mỗi lần gọi, thêm kết quả vào all_rows.
        while True:
            # Lấy danh sách người dùng theo trang với page_size=200. Nếu có lỗi, trả về kết quả lỗi.
            result = self.list_users_page(page, 200)

            if not result['success']:
                return result

            # Nếu có người dùng, thêm vào all_rows. Nếu không còn người dùng nào, thoát khỏi vòng lặp.
            all_rows.extend(result['users'])
            if len(result['users']) < 200:
                break

            # Tăng page lên 1 để lấy trang tiếp theo.
            page += 1

        # Chỉ định các cột cố định để trả về, và chuẩn hóa dữ liệu thành dạng tuple cho data.
        cols = ['UserId','UserName', 'Email', 'IsActivate', 'ActivatedAt', 'Privilege', 'AuthVersion']
        data = [tuple(r[c] for c in cols) for r in all_rows]
        return self._success([{'columns': cols, 'data': data, 'records': all_rows}])

    def get_username(self, email):
        """
        Lấy tên người dùng từ email.
        """
        result = self.get_user(email)
        if result['success']:
            result.update(columns=['UserName'], data=[(result['user']['UserName'],)])
        return result

    def _hash_password(self, password):
        """
        Mã hóa mật khẩu bằng thuật toán scrypt, trả về (salt, hashed).
        """
        # Kiểm tra mật khẩu không rỗng, không chứa null, và không vượt quá giới hạn UTF-16 code units.
        password = _text(password, 'Mật khẩu', 1024, strip=False)
        # Hash mật khẩu bằng hàm hash. Trả về (salt, hashed).
        salt, hashed = Hash.scrypt(password)
        # Kiểm tra salt và hashed không rỗng, không chứa null, và không vượt quá giới hạn UTF-16 code units.
        hashed = _text(hashed, 'PasswordHash', 500, strip=False)
        salt = None if salt is None else _text(salt, 'PasswordSalt', 500, strip=False)
        return salt, hashed

    def create_new_user(self, username, email, password, privilege='User', *,
                        full_name=None, phone_number=None, date_of_birth=None,
                        address=None, avatar_url=None):
        """
        Tạo tài khoản mới với quyền User mặc định. Nếu privilege khác 'User', raise ValueError.
        """
        if privilege != 'User':
            raise ValueError('Đăng ký mới chỉ cấp User. Các quyền khác phải do admin cấp sau.')
        
        username = _text(username, 'Tên hiển thị', 200)
        salt, hashed = self._hash_password(password)

        # Gọi stored procedure 'usp_User_RegisterLocal' với các tham số đã chuẩn hóa. Nếu full_name là None, sẽ dùng username làm full_name.
        return self._call('register', _email(email), username, hashed, salt,
                          _text(full_name if full_name is not None else username, 'Họ tên', 200),
                          _optional(phone_number, 'SĐT', 30), _dob(date_of_birth),
                          _optional(address, 'Địa chỉ', 500), _optional(avatar_url, 'Ảnh', 2048))

    def update_user_profile(self, email=None, *, user_id=None, username=None,
                            full_name=UNSET, phone_number=UNSET, date_of_birth=UNSET,
                            address=UNSET, avatar_url=UNSET):
        """
        Cập nhật hồ sơ người dùng.
        Nếu một trường là UNSET thì không thay đổi, nếu là None thì xóa giá trị, nếu có giá trị thì cập nhật.
        """
        # Chuẩn hóa user_id và email, raise ValueError nếu cả hai đều không hợp lệ.
        args = list(_who(user_id, email))
        args.append(None if username is None else _text(username, 'Tên hiển thị', 200))

        # Kiểm tra và chuẩn hóa các trường full_name, phone_number, date_of_birth, address, avatar_url.
        # Nếu giá trị là UNSET thì không thay đổi, nếu là None thì xóa giá trị, nếu có giá trị thì cập nhật.
        for value, name, size in ((full_name, 'Họ tên', 200), (phone_number, 'SĐT', 30), (date_of_birth, 'Ngày sinh', None), (address, 'Địa chỉ', 500), (avatar_url, 'Ảnh', 2048)):
            # Thêm vào args theo thứ tự của stored procedure.
            if value is UNSET:
                args.extend((None, False))
            else:
                args.extend((_dob(value) if size is None else _optional(value, name, size), True))

        # Gọi stored procedure 'usp_User_UpdateProfile' với các tham số đã chuẩn hóa. Nếu có lỗi, trả về kết quả lỗi.
        return self._call('profile', *args)

    def activate_user(self, email=None, activate=True, *, user_id=None):
        """
        Kích hoạt hoặc vô hiệu hóa tài khoản người dùng.
        - Nếu activate=True, sẽ kích hoạt tài khoản.
        - Nếu activate=False, sẽ vô hiệu hóa tài khoản.
        """
        if type(activate) is not bool:
            raise ValueError('activate phải là bool')
        return self._call('activate' if activate else 'deactivate', *_who(user_id, email))

    def set_user_status(self, status, email=None, *, user_id=None):
        """
        Thiết lập trạng thái cho người dùng.
        - status: chuỗi tối đa 50 ký tự, có thể rỗng hoặc None để xóa trạng thái.
        """
        return self._call('status', _optional(status, 'Status', 50), *_who(user_id, email))

    def change_email_user(self, new_email, email=None, *, user_id=None):
        """
        Thay đổi email của người dùng.
        - new_email: email mới.
        - email: email hiện tại (nếu có).
        - user_id: ID của người dùng (nếu có).
        """
        # Chỉ gọi sau xác thực lại + xác minh email mới ở tầng nghiệp vụ.
        return self._call('email', _email(new_email), *_who(user_id, email))

    def delete_account(self, email=None, *, user_id=None):
        """
        Xóa tài khoản người dùng.
        - email: email của người dùng (nếu có).
        - user_id: ID của người dùng (nếu có).
        """
        # FK CASCADE xóa hồ sơ/liên kết và bảng V2. FK bảng khác có thể chặn.
        return self._call('delete', *_who(user_id, email))

    def get_local_credentials(self, email):
        """
        Lấy thông tin xác thực cục bộ của người dùng.
        - email: email của người dùng.
        """
        # Chỉ backend được nhận hash/salt; không trả result này ra HTTP/UI.
        return self._call('credentials', _email(email))

    def get_password_salt_password_privilege_user(self, email):
        """
        Lấy thông tin mật khẩu, salt, và quyền của người dùng.
        - email: email của người dùng.
        - return: thông tin mật khẩu, salt, và quyền của người dùng.
        - return type: dict
        """
        # Lấy thông tin xác thực cục bộ của người dùng. Nếu không thành công hoặc không có bản ghi, trả về kết quả lỗi.
        result = self.get_local_credentials(email)
        if not result['success'] or not result['records']:
            return result

        # Lấy thông tin hồ sơ người dùng từ user_id trong bản ghi xác thực. Nếu không thành công, trả về kết quả lỗi.
        credential = result['records'][0]
        # Lấy thông tin hồ sơ người dùng từ user_id trong bản ghi xác thực. Nếu không thành công, trả về kết quả lỗi.
        profile = self.get_user(user_id=credential['UserId'])
        if not profile['success']:
            return profile

        # Chuẩn hóa dữ liệu trả về: chỉ giữ các cột cần thiết và thêm thông tin ActivatedAt và Privilege từ hồ sơ người dùng.
        cols = ['PasswordHash', 'PasswordSalt', 'IsActivate', 'ActivatedAt', 'Privilege', 'UserId', 'AuthVersion']
        row = {**credential, 'ActivatedAt': profile['user']['ActivatedAt'],
               'Privilege': profile['user']['Privilege']}

        # Cập nhật lại kết quả với các cột cần thiết và dữ liệu đã chuẩn hóa.
        result.update(columns=cols, data=[tuple(row[c] for c in cols)], records=[row])
        return result

    def record_local_login(self, user_id, expected_auth_version):
        """
        Ghi nhận lần đăng nhập cục bộ của người dùng.
        - user_id: ID của người dùng.
        - expected_auth_version: phiên bản xác thực mong đợi, dùng để kiểm tra race condition. Nếu không khớp, procedure sẽ trả về lỗi.
        """
        return self._call('login', _text(_user_id(user_id), 'UserId', 16),
                          _positive(expected_auth_version, 'AuthVersion', 2147483647))

    def update_last_login_at(self, email, *, expected_auth_version=None):
        """
        Cập nhật thời gian đăng nhập cuối cùng của người dùng.
        - email: email của người dùng.
        - expected_auth_version: phiên bản xác thực mong đợi, dùng để kiểm tra race condition. Nếu không khớp, procedure sẽ trả về lỗi.
        Adapter cũ phải truyền version từ bước verify mật khẩu.
        OAuth đã cập nhật LastLoginAt trong procedure external, không gọi hàm này.
        """
        if expected_auth_version is None:
            raise ValueError('Phải truyền AuthVersion từ bước xác thực mật khẩu')
        result = self.get_user(email)
        return self.record_local_login(result['user']['UserId'], expected_auth_version) if result['success'] else result

    def login_local(self, email, password):
        """
        Đăng nhập cục bộ bằng email và mật khẩu.
        - email: email của người dùng.
        - password: mật khẩu của người dùng.
        """
        # Kiểm tra email và password không rỗng, không chứa null, và không vượt quá giới hạn UTF-16 code units.
        email = _email(email)
        password = _text(password, 'Mật khẩu', 1024, strip=False)

        # Truy vấn thông tin xác thực cục bộ của người dùng. Nếu không thành công hoặc không có bản ghi, trả về kết quả lỗi.
        result = self.get_local_credentials(email)

        if not result['success']:
            return result
        if not result['records']:
            return _error('INVALID_CREDENTIALS', 'Email hoặc mật khẩu không đúng.')

        # Lấy thông tin người dùng từ bản ghi xác thực. Nếu không có PasswordHash hoặc PasswordSalt, trả về lỗi.
        user = result['records'][0]
        try:
            valid = user['PasswordHash'] is not None and Hash.verify(user['PasswordSalt'], user['PasswordHash'], password) is True
        except Exception as e: # pylint: disable=broad-except
            logger.error('Lỗi khi kiểm tra mật khẩu: %s', str(e))
            return _error('HASH_VERIFY_ERROR', 'Không kiểm tra được dữ liệu mật khẩu.')

        if not valid:
            return _error('INVALID_CREDENTIALS', 'Email hoặc mật khẩu không đúng.')

        # SP kiểm tra IsActivate và ExpectedAuthVersion.
        return self.record_local_login(user['UserId'], user['AuthVersion'])

    def update_password_user(self, email, password=None, *, user_id=None, expected_auth_version=None):
        """
        Cập nhật mật khẩu cho người dùng.
        - email: email của người dùng.
        - password: mật khẩu mới.
        - user_id: ID của người dùng.
        - expected_auth_version: phiên bản xác thực mong đợi, dùng để kiểm tra race condition. Nếu không khớp, procedure sẽ trả về lỗi.
        """
        # Kiểm tra email và password không rỗng, không chứa null, và không vượt quá giới hạn UTF-16 code units.
        email = _email(email)
        password = _text(password, 'Mật khẩu', 1024, strip=False)

        # Kiểm tra expected_auth_version là số nguyên dương, nếu không hợp lệ thì raise ValueError.
        version = _positive(expected_auth_version, 'AuthVersion đã xác thực', 2147483647)

        # Nếu user_id không được cung cấp, lấy user_id từ email. Nếu không tìm thấy người dùng, trả về kết quả lỗi.
        if user_id is None:
            result = self.get_user(email)
            if not result['success']:
                return result
            user_id = result['user']['UserId']

        # Hash mật khẩu mới bằng thuật toán scrypt, trả về salt và hashed. Sau đó gọi stored procedure 'usp_User_UpdatePassword' với user_id, hashed, version và salt.
        salt, hashed = self._hash_password(password)
        return self._call('password', _text(_user_id(user_id), 'UserId', 16), hashed, version, salt)

    @staticmethod
    def _provider(provider, provider_id):
        """
        Chuẩn hóa provider và provider_id.
        - provider: tên nhà cung cấp (ví dụ: 'google', 'facebook'), sẽ được chuyển thành chữ thường.
        - provider_id: ID của người dùng từ nhà cung cấp, sẽ được giữ nguyên (không strip/lower) vì có thể là chuỗi opaque.
        """
        provider = _text(provider, 'Provider', 50).lower()
        if provider not in {'google', 'facebook'}:
            raise ValueError('Provider không hỗ trợ')

        # ID opaque: không strip/lower nội dung do provider cấp.
        provider_id = _text(provider_id, 'ProviderUserId', 255, strip=False)
        if not provider_id.strip():
            raise ValueError('ProviderUserId không được rỗng')

        # Trả về provider và provider_id đã chuẩn hóa.
        return provider, provider_id

    def resolve_or_register_external_user(self, provider, provider_user_id,
                                          provider_email=None, display_name=None, *,
                                          account_email=None, full_name=None,
                                          phone_number=None, date_of_birth=None,
                                          address=None, avatar_url=None):
        """
        Giải quyết hoặc đăng ký người dùng bên ngoài.
        - provider: tên nhà cung cấp (ví dụ: 'google', 'facebook').
        - provider_user_id: ID của người dùng từ nhà cung cấp.
        - provider_email: email từ nhà cung cấp.
        - display_name: tên hiển thị.
        - account_email: email chính đã xác minh.
        - full_name: họ tên đầy đủ.
        - phone_number: số điện thoại.
        - date_of_birth: ngày sinh.
        - address: địa chỉ.
        - avatar_url: URL ảnh đại diện.
        """
        # Chuẩn hóa provider và provider_user_id, nếu không hợp lệ thì raise ValueError.
        provider, provider_user_id = self._provider(provider, provider_user_id)

        # Gọi stored procedure 'usp_User_ExternalLogin' với các tham số đã chuẩn hóa. Nếu có lỗi, trả về kết quả lỗi.
        result = self._call('external', provider, provider_user_id,
            _email(account_email, optional=True), _optional(provider_email, 'ProviderEmail', 320),
            _optional(display_name, 'Tên hiển thị', 200), _optional(full_name, 'Họ tên', 200),
            _optional(phone_number, 'SĐT', 30), _dob(date_of_birth),
            _optional(address, 'Địa chỉ', 500), _optional(avatar_url, 'Ảnh', 2048))

        return result

    def link_external_account(self, user_id, provider, provider_user_id, provider_email=None):
        """
        Liên kết tài khoản bên ngoài với người dùng hiện tại.
        - user_id: ID của người dùng hiện tại.
        - provider: tên nhà cung cấp (ví dụ: 'google', 'facebook').
        - provider_user_id: ID của người dùng từ nhà cung cấp.
        - provider_email: email từ nhà cung cấp (tùy chọn).
        """
        # Chuẩn hóa provider và provider_user_id, nếu không hợp lệ thì raise ValueError.
        provider, provider_user_id = self._provider(provider, provider_user_id)
        # gọi stored procedure 'usp_User_LinkExternal' với các tham số đã chuẩn hóa. Nếu có lỗi, trả về kết quả lỗi.
        return self._call('link', _text(_user_id(user_id), 'UserId', 16), provider,
                          provider_user_id, _optional(provider_email, 'ProviderEmail', 320))

    def link_google_account(self, user_email, google_id, google_email=None):
        """
        Liên kết tài khoản Google với người dùng hiện tại.
        - user_email: email của người dùng hiện tại.
        - google_id: ID của người dùng Google.
        - google_email: email của người dùng Google (tùy chọn).
        """
        # Lấy thông tin người dùng từ email. Nếu không thành công, trả về kết quả lỗi.
        result = self.get_user(user_email)
        return self.link_external_account(result['user']['UserId'], 'google', google_id, google_email) if result['success'] else result

    def unlink_external_account(self, user_id, provider, provider_user_id):
        """
        Hủy liên kết tài khoản bên ngoài khỏi người dùng hiện tại.
        - user_id: ID của người dùng hiện tại.
        - provider: tên nhà cung cấp (ví dụ: 'google', 'facebook').
        - provider_user_id: ID của người dùng từ nhà cung cấp.
        """
        # Chuẩn hóa provider và provider_user_id, nếu không hợp lệ thì raise ValueError.
        provider, provider_user_id = self._provider(provider, provider_user_id)
        return self._call('unlink', _text(_user_id(user_id), 'UserId', 16), provider, provider_user_id)

    # SQL phụ dùng cùng tên application lock với bộ SP để tránh thứ tự khóa ngược.
    def _lock_user(self, cursor, email=None, user_id=None):
        """
        Khóa người dùng để tránh race condition khi cập nhật thông tin.
        - cursor: con trỏ cơ sở dữ liệu đang mở.
        - email: email của người dùng (tùy chọn).
        - user_id: ID của người dùng (tùy chọn).
        """
        # Chuẩn hóa email và user_id, nếu cả hai đều không hợp lệ thì raise ValueError.
        uid, address = _who(user_id, email)

        # Sử dụng sp_getapplock để khóa tài nguyên 'UserManagement.Write' với chế độ Exclusive và LockOwner là Transaction.
        # Nếu không lấy được khóa trong 10 giây, sẽ ném lỗi 51103 với thông báo 'Busy'.
        cursor.execute("""DECLARE @rc INT;
            EXEC @rc=sys.sp_getapplock @Resource=N'UserManagement.Write',
                @LockMode=N'Exclusive',@LockOwner=N'Transaction',@LockTimeout=10000;
            IF @rc<0 THROW 51103,N'Busy',1;""")

        # Sau khi lấy được khóa, truy vấn thông tin người dùng với UPDLOCK và HOLDLOCK để tránh race condition
        self._read_sets(cursor)
        query = 'SELECT UserId,Email,IsActivate,AuthVersion FROM dbo.Users WITH(UPDLOCK,HOLDLOCK) '

        # Nếu user_id được cung cấp, truy vấn theo UserId. Nếu không, truy vấn theo email (sau khi chuẩn hóa và loại bỏ khoảng trắng).
        if uid:
            cursor.execute(query + 'WHERE UserId=?', (uid,))
        else:
            cursor.execute(query + 'WHERE LOWER(LTRIM(RTRIM(Email)))=? COLLATE Latin1_General_100_CI_AS', (address,))

        # Đọc kết quả từ con trỏ và kiểm tra xem có đúng một bản ghi hay không. Nếu không, ném lỗi DatabaseError.
        sets = self._read_sets(cursor)
        rows = sets[0]['records'] if sets else []
        if len(rows) != 1:
            raise DatabaseError('Không tìm được một tài khoản duy nhất')

        return rows[0]

    def change_role_user(self, privilege, email=None, *, user_id=None):
        """
        Thay đổi quyền của người dùng.
        - privilege: quyền mới.
        - email: email của người dùng (tùy chọn).
        - user_id: ID của người dùng (tùy chọn).
        """
        # Chuẩn hóa privilege, nếu không hợp lệ thì raise ValueError.
        privilege = _text(privilege, 'Quyền', 50)
        try:
            # Sử dụng transaction để đảm bảo tính nhất quán khi thay đổi quyền của người dùng.
            with self._transaction() as cursor:
                # Khóa người dùng để tránh race condition. Vì nó có thể gặp trường hợp race condition như:
                # 1. Hai admin cùng thay đổi quyền của một user
                # 2. Một admin thay đổi quyền của user trong khi user đang đăng nhập và tạo session mới.
                user = self._lock_user(cursor, email, user_id)

                # Cập nhật quyền của người dùng trong bảng Users, đồng thời tăng AuthVersion lên 1 để invalid các session cũ.
                cursor.execute("""
                    UPDATE dbo.Users 
                    SET 
                        Privilege=?,
                        UpdatedAt=SYSUTCDATETIME(),
                        AuthVersion=AuthVersion+1
                    OUTPUT 
                        inserted.UserId,
                        inserted.Email,
                        inserted.Privilege,
                        inserted.AuthVersion
                    WHERE UserId=?
                    """, (privilege, user['UserId']))

                # Đọc kết quả từ con trỏ và trả về kết quả thành công với các bản ghi đã cập nhật.
                sets = self._read_sets(cursor)

            # Khi ra khỏi hàm with thì khóa sẽ được release, và transaction sẽ commit nếu không có lỗi.
            return self._success(sets)

        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi thay đổi quyền người dùng: %s', str(exc))
            return self._failure(exc)

    def create_session_by_email(self, email, days=30, device_info=None, *, expected_auth_version=None, user_id=None):
        """
        Tạo phiên đăng nhập mới cho người dùng đã xác thực.
        - email: email của người dùng.
        - days: số ngày phiên đăng nhập có hiệu lực (mặc định 30).
        - device_info: thông tin thiết bị (tùy chọn).
        - expected_auth_version: phiên bản xác thực mong muốn.
        - user_id: ID của người dùng (tùy chọn).
        """
        # Xác thực các tham số: email không được rỗng, expected_auth_version là số nguyên dương, days là số nguyên dương, device_info là chuỗi tùy chọn.
        if not email:
            return self._failure(ValueError('Email là bắt buộc.'))
        version = _positive(expected_auth_version, 'AuthVersion đã xác thực', 2147483647)
        days = _positive(days, 'Thời gian ghi nhớ', 30)
        device_info = _optional(device_info, 'Thiết bị', 256)

        # Tạo token ngẫu nhiên để sử dụng làm khóa phiên đăng nhập. Token này sẽ được hash trước khi lưu vào cơ sở dữ liệu.
        token = secrets.token_urlsafe(32)
        try:
            # Sử dụng transaction để đảm bảo tính nhất quán khi tạo phiên đăng nhập mới.
            with self._transaction() as cursor:
                # Khóa người dùng để tránh race condition.
                user = self._lock_user(cursor, email, user_id)

                # Kiểm tra xem người dùng có được kích hoạt và phiên bản xác thực có khớp với expected_auth_version hay không. Nếu không, trả về lỗi AUTH_CHANGED.
                if not user['IsActivate'] or user['AuthVersion'] != version:
                    result = _error('AUTH_CHANGED', 'Tài khoản/phiên bản xác thực đã thay đổi.')
                    result['token'] = None
                    return result

                # Chèn một bản ghi mới vào bảng AuthSessions với thông tin người dùng, token hash, thời gian hết hạn và thông tin thiết bị.
                cursor.execute("""
                    INSERT dbo.AuthSessions
                        (UserId, UserEmail, AuthVersion,TokenHash,ExpiresAt,DeviceInfo)
                    OUTPUT 
                        inserted.SessionId,
                        inserted.ExpiresAt
                    VALUES
                        (?,?,?,?,DATEADD(DAY,?,SYSUTCDATETIME()),?)
                    """, (user['UserId'], email, version, _token_hash(token), days, device_info))

                # Đọc kết quả từ con trỏ và lấy bản ghi vừa chèn vào. Nếu không có bản ghi nào, ném lỗi DatabaseError.
                sets = self._read_sets(cursor)
                row = sets[0]['records'][0]

                if not row:
                    raise DatabaseError('Không tạo được phiên đăng nhập mới.')

            # Với transaction đã commit, trả về kết quả thành công với token, session_id và thời gian hết hạn của phiên đăng nhập mới.
            result = self._success(sets, 'Đã tạo phiên.')
            result.update(token=token, session_id=row['SessionId'], expires_at=_utc(row['ExpiresAt']).isoformat())
            return result

        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi tạo phiên đăng nhập: %s', str(exc))
            result = self._failure(exc)
            result['token'] = None
            return result

    def get_user_by_session(self, session_token):
        """
        Lấy thông tin người dùng từ token phiên đăng nhập.
        - session_token: token phiên đăng nhập.
        """
        # Lấy thông tin người dùng từ token phiên đăng nhập bằng cách truy vấn bảng AuthSessions và Users. Nếu không tìm thấy bản ghi nào, trả về lỗi INVALID_SESSION.
        result = self._execute_query("""
            SELECT 
                u.UserName,
                u.Email,
                u.IsActivate,
                u.Privilege,
                u.Status,
                s.ExpiresAt,
                u.UserId,
                u.AuthVersion,
                s.SessionId
            FROM dbo.AuthSessions s 
            JOIN dbo.Users u 
            ON u.UserId=s.UserId
            WHERE 
                s.TokenHash=? 
                AND s.RevokedAt IS NULL
                AND s.ExpiresAt>SYSUTCDATETIME() 
                AND u.IsActivate=1
                AND s.AuthVersion=u.AuthVersion
            """, (_token_hash(session_token),), transactional=False)

        if result['success']:
            if not result['records']:
                return _error('INVALID_SESSION', 'Phiên không hợp lệ hoặc đã hết hạn.')

            # Đồng bộ timezone trong records/data/result_sets, không tạo Status giả bằng 1.
            for row in result['records']:
                row['ExpiresAt'] = _utc(row['ExpiresAt'])

            # Chuẩn hóa dữ liệu trả về: chỉ giữ các cột cần thiết và thêm thông tin người dùng từ bản ghi.
            result['data'] = [tuple(r[c] for c in result['columns']) for r in result['records']]
            result['result_sets'][0]['data'] = result['data']
            result['user'] = result['records'][0]
        return result

    def revoke_session(self, session_token):
        """
        Thu hồi phiên đăng nhập hiện tại bằng token.
        - session_token: token phiên đăng nhập.
        """
        if not session_token:
            return self._success(message='Không có phiên cần thu hồi.')
        return self._execute_query("""UPDATE dbo.AuthSessions SET RevokedAt=SYSUTCDATETIME()
            WHERE TokenHash=? AND RevokedAt IS NULL""", (_token_hash(session_token),))

    def revoke_all_sessions_by_email(self, email):
        """
        Thu hồi tất cả phiên đăng nhập của người dùng bằng email.
        - email: email của người dùng.
        """
        try:
            with self._transaction() as cursor:
                user = self._lock_user(cursor, email)
                # Cùng lock với create_session: phiên tạo trước bị thu hồi, phiên tạo sau chỉ hợp lệ khi dùng AuthVersion mới từ lần xác thực mới.
                # Cập nhật AuthVersion của người dùng để tất cả phiên đăng nhập cũ bị vô hiệu hóa.
                cursor.execute('UPDATE dbo.Users SET AuthVersion=AuthVersion+1,UpdatedAt=SYSUTCDATETIME() WHERE UserId=?', (user['UserId'],))
                self._read_sets(cursor)

                # Thu hồi tất cả phiên đăng nhập chưa bị thu hồi của người dùng.
                cursor.execute('UPDATE dbo.AuthSessions SET RevokedAt=SYSUTCDATETIME() WHERE UserId=? AND RevokedAt IS NULL', (user['UserId'],))
                sets = self._read_sets(cursor)
            return self._success(sets)

        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi thu hồi tất cả phiên đăng nhập: %s', str(exc))
            return self._failure(exc)

    def revoke_session_by_id(self, session_id, email):
        """
        Thu hồi một phiên đăng nhập cụ thể bằng session_id và email của người dùng.
        - session_id: ID của phiên đăng nhập.
        - email: email của người dùng.
        """
        # Chuyển session_id sang số nguyên dương, nếu không hợp lệ thì raise ValueError.
        session_id = _positive(session_id, 'SessionId')
        try:
            with self._transaction() as cursor:
                user = self._lock_user(cursor, email)
                cursor.execute("""
                    UPDATE dbo.AuthSessions 
                    SET RevokedAt=SYSUTCDATETIME()
                    WHERE 
                    SessionId=? 
                    AND UserId=? 
                    AND RevokedAt IS NULL
                """, (session_id, user['UserId']))
                sets = self._read_sets(cursor)

            return self._success(sets)

        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi thu hồi phiên đăng nhập: %s', str(exc))
            return self._failure(exc)

    def list_sessions_by_email(self, email, limit=100):
        """
        Liệt kê các phiên đăng nhập của người dùng theo email.
        - email: email của người dùng.
        - limit: số lượng phiên đăng nhập cần lấy.
        """
        limit = _positive(limit, 'limit', 500)
        profile = self.get_user(email)
        if not profile['success']:
            return profile

        # Chạy truy vấn để lấy các phiên đăng nhập chưa bị thu hồi và chưa hết hạn của người dùng, sắp xếp theo SessionId giảm dần và giới hạn số lượng bản ghi trả về.
        return self._execute_query("""
            SELECT TOP (?) 
                s.SessionId,
                s.DeviceInfo,
                s.CreatedAt,
                s.ExpiresAt
            FROM dbo.AuthSessions s 
            JOIN dbo.Users u 
            ON u.UserId=s.UserId
            WHERE 
                s.UserId=? 
                AND s.RevokedAt IS NULL 
                AND s.ExpiresAt>SYSUTCDATETIME()
                AND u.IsActivate=1 
                AND s.AuthVersion=u.AuthVersion 
                ORDER BY s.SessionId DESC
                """,(limit, profile['user']['UserId']), transactional=False)

    def cleanup_expired_sessions(self, batch_size=1000, retention_days=30):
        """
        Xóa các phiên đăng nhập đã hết hạn hoặc bị thu hồi quá lâu.
        - batch_size: số lượng phiên đăng nhập cần xóa trong một lần thực hiện.
        - retention_days: số ngày giữ lại phiên đăng nhập trước khi xóa.
        """
        # Kiểm tra batch_size và retention_days là số nguyên dương, nếu không hợp lệ thì raise ValueError.
        batch_size = _positive(batch_size, 'batch_size', 10000)
        retention_days = _positive(retention_days, 'retention_days', 365)

        return self._execute_query("""
            DELETE TOP (?) 
            FROM dbo.AuthSessions 
            OUTPUT deleted.SessionId
            WHERE 
                ExpiresAt<DATEADD(DAY,-?,SYSUTCDATETIME())
                OR
                RevokedAt<DATEADD(DAY,-?,SYSUTCDATETIME())
            """, (batch_size, retention_days, retention_days))

    def _otp_digest(self, user_id, purpose, challenge_id, otp):
        """
        Tạo HMAC-SHA256 từ user_id, purpose, challenge_id và otp.
        - user_id: ID của người dùng.
        - purpose: Mục đích của OTP.
        - challenge_id: ID của lần phát hành OTP.
        - otp: Mã OTP.
        """
        # UserId/purpose/challenge ngăn dùng mã của người/mục đích/lần phát hành khác.
        payload = '\x00'.join((user_id, purpose, challenge_id, otp)).encode()
        return hmac.new(b'123456', payload, hashlib.sha256).digest()

    def update_otp_and_time_expired(self, email, otp, time_expired, purpose='reset_password'):
        """
        Lưu mã OTP và thời gian hết hạn vào cơ sở dữ liệu.
        - email: email của người dùng.
        - otp: mã OTP.
        - time_expired: thời gian hết hạn của OTP (datetime có timezone).
        - purpose: mục đích của OTP (mặc định là 'reset_password').
        - return: kết quả thành công hoặc thất bại.
        """
        # Kiểm tra và chuẩn hóa các tham số đầu vào: email, purpose, otp và time_expired. Nếu time_expired không phải là datetime có timezone, ném ValueError.
        email, purpose = _email(email), _text(purpose, 'Purpose', 100)
        otp = _text(otp, 'OTP', 50, strip=False)
        if not isinstance(time_expired, datetime) or time_expired.tzinfo is None or time_expired.utcoffset() is None:
            raise ValueError('Hạn OTP phải là datetime có timezone')
        expires = time_expired.astimezone(timezone.utc).replace(tzinfo=None)

        # Tạo challenge_id ngẫu nhiên để phân biệt các lần phát hành OTP khác nhau.
        challenge_id = uuid.uuid4().hex
        try:
            with self._transaction() as cursor:
                user = self._lock_user(cursor, email)
                # Tạo digest từ user_id, purpose, challenge_id và otp để lưu vào cơ sở dữ liệu.
                digest = self._otp_digest(user['UserId'], purpose, challenge_id, otp)
                # Thực hiện truy vấn SQL để kiểm tra thời gian hết hạn, xóa các bản ghi OTP cũ và chèn bản ghi OTP mới vào bảng UserOTP.
                # Nếu thời gian hết hạn không hợp lệ, ném lỗi 51300 với thông báo 'OTP expiration invalid'.
                cursor.execute("""
                    DECLARE @Expires DATETIME2(7)=?;
                    IF @Expires<=SYSUTCDATETIME() OR @Expires>DATEADD(MINUTE,15,SYSUTCDATETIME())
                        THROW 51300,N'OTP expiration invalid',1;
                    DELETE dbo.UserOTP 
                    WHERE 
                        UserId=? 
                        AND Purpose=?;
                    INSERT dbo.UserOTP
                        (UserId,Purpose,ChallengeId,CodeHash,ExpiresAt,AuthVersion)
                    OUTPUT 
                        inserted.ChallengeId,
                        inserted.ExpiresAt
                    VALUES
                        (?,?,?,?,@Expires,?);
                    """, (expires, user['UserId'], purpose, user['UserId'], purpose, challenge_id, digest, user['AuthVersion']))

                # Đọc kết quả từ con trỏ và trả về kết quả thành công với các bản ghi đã chèn vào.
                sets = self._read_sets(cursor)
            return self._success(sets, 'Đã lưu mã xác minh; gửi mã qua tầng nghiệp vụ.')
        except DatabaseError:
            raise
        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi lưu mã OTP: %s', str(exc))
            return self._failure(exc)

    def get_otp_and_expired_time(self, email, purpose='reset_password'):
        """
        API cũ trả plaintext OTP đã bỏ. Dùng verify_and_consume_otp để so mã.
        Không trả một cấu trúc khác dưới cùng tên vì caller cũ có thể xác thực sai.
        """
        raise DatabaseError('Không đọc OTP plaintext; chuyển sang verify_and_consume_otp(email, otp, purpose)')

    def verify_and_consume_otp(self, email, otp, purpose='reset_password'):
        """
        So mã constant-time, tối đa 5 lần thử, hết hạn hoặc dùng rồi thì từ chối.
        Kết quả chứa UserId/AuthVersion để tầng nghiệp vụ thực hiện đúng hành động.
        Đầu vào purpose phải do endpoint quyết định, không tin client tự chọn.
        Khi hành động sau thất bại, yêu cầu mã mới; OTP đã dùng không được phục hồi.
        """
        # Kiểm tra và chuẩn hóa các tham số đầu vào:
        email, purpose = _email(email), _text(purpose, 'Purpose', 100)
        otp = _text(otp, 'OTP', 50, strip=False)
        try:
            with self._transaction() as cursor:
                user = self._lock_user(cursor, email)
                # Truy vấn cơ sở dữ liệu để lấy ChallengeId, CodeHash và AuthVersion từ bảng UserOTP với các điều kiện: UserId, Purpose, ConsumedAt là NULL, ExpiresAt lớn hơn thời gian hiện tại và Attempts nhỏ hơn 5.
                cursor.execute("""
                    SELECT 
                        ChallengeId,
                        CodeHash,
                        AuthVersion 
                    FROM dbo.UserOTP
                    WITH(UPDLOCK,HOLDLOCK) 
                    WHERE 
                        UserId=?
                        AND Purpose=?
                        AND ConsumedAt IS NULL
                        AND ExpiresAt>SYSUTCDATETIME()
                        AND Attempts<5
                    """, (user['UserId'], purpose))

                # Đọc kết quả từ con trỏ và kiểm tra xem có bản ghi nào hay không. Nếu không có bản ghi hoặc AuthVersion không khớp, trả về lỗi INVALID_OTP.
                sets = self._read_sets(cursor)
                rows = sets[0]['records'] if sets else []

                if not rows or rows[0]['AuthVersion'] != user['AuthVersion']:
                    return _error('INVALID_OTP', 'Mã xác minh không hợp lệ hoặc hết hạn.')

                # Lấy bản ghi đầu tiên và tạo digest từ user_id, purpose, challenge_id và otp để so sánh với CodeHash trong cơ sở dữ liệu. Nếu không hợp lệ, cập nhật số lần thử và thời gian sử dụng.
                row = rows[0]
                expected = self._otp_digest(user['UserId'], purpose, row['ChallengeId'], otp)
                # So sánh constant-time giữa expected và CodeHash trong cơ sở dữ liệu để tránh timing attack.
                valid = hmac.compare_digest(expected, bytes(row['CodeHash']))
                # Tăng số lần thử và cập nhật thời gian sử dụng nếu mã không hợp lệ. Nếu mã hợp lệ, chỉ tăng số lần thử.
                cursor.execute("""
                    UPDATE dbo.UserOTP 
                    SET 
                        Attempts=Attempts+1,
                        -- Cập nhật thời gian sử dụng nếu mã không hợp lệ
                        ConsumedAt= CASE 
                                    WHEN ?=1 
                                    THEN SYSUTCDATETIME()
                                    ELSE ConsumedAt
                                    END
                    WHERE 
                        UserId=?
                        AND Purpose=?
                    """, (int(valid), user['UserId'], purpose))
                self._read_sets(cursor)

            # Nếu mã không hợp lệ, cập nhật số lần thử và thời gian sử dụng.
            if not valid:
                return _error('INVALID_OTP', 'Mã xác minh không hợp lệ hoặc hết hạn.')

            result = self._success(message='Đã xác minh và sử dụng mã.')
            result.update(user_id=user['UserId'], auth_version=user['AuthVersion'], purpose=purpose)
            return result

        except DatabaseError:
            raise
        except Exception as exc: # pylint: disable=broad-except
            logger.error('Lỗi khi xác minh mã OTP: %s', str(exc))
            return self._failure(exc)

if __name__ == '__main__':
    driver_SQL = get_odbc_drivers_for_sql_server()  # Kiểm tra driver ODBC SQL Server có sẵn.
    print('ODBC drivers for SQL Server:', driver_SQL)
