"""
Adapter xử lý các quá trình đăng nhập của người dùng
"""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from services.database_service import MyDatabase
from services.hash import Hash

# Thời gian ghi nhớ đăng nhập (ngày)
REMEMBER_DAYS = 30
# Nếu DB lưu UTC naive: đổi thành timezone.utc. Tốt nhất API trả ISO 8601 có offset.
LEGACY_DB_TIMEZONE = timezone(timedelta(hours=7)) # Múi giờ +7 của Vietnam

class AuthError(RuntimeError):
    """
    Thông báo đã làm sạch, có thể hiển thị cho user.
    """

class InvalidCredentials(AuthError):
    """
    email/mật khẩu sai hoặc tài khoản không được phép đăng nhập
    """

class InvalidSession(AuthError):
    """
    phiên hết hạn, bị thu hồi hoặc không hợp lệ.
    """

class BackendUnavailable(AuthError):
    """
    DB không truy cập được hoặc kết quả backend sai định dạng.
    """

class AccountLinkRequired(AuthError):
    """
    Cần đăng nhập tài khoản nội bộ để liên kết provider.
    """

class AccountPendingApproval(AuthError):
    """
    Tài khoản mới đã tạo, đang chờ admin kích hoạt.
    """

class AccountInactive(AuthError):
    """
    Tài khoản hiện chưa được kích hoạt hoặc đã bị khóa.
    """


@dataclass(frozen=True)
class AuthSession:
    """
    Lớp chứa kết quả đăng nhập  
    Không cho phép người dùng sửa đổi thông tin của các trường khi đã khởi tạo nó với frozen
    """
    email: str                                              # Email của tài khoản
    permission: str                                         # Quyền do DB trả về
    provider: str = "local"                                 # Mặc định đăng nhập bằng mật khẩu; có thể là Google/Facebook
    token: str | None = field(default=None, repr=False)     # Token ghi nhớ; mặc định không có; ẩn khỏi repr()
    expires_at: datetime | None = None                      # Thời điểm hết hạn token
    warning: str | None = None                              # Cảnh báo đi kèm dù đăng nhập thành công
    newly_issued: bool = False                              # Đánh dấu token vừa được cấp trong thao tác này

    def record(self):
        """
        Hàm lấy dữ liệu để ghi một phiên ghi nhớ đăng nhập
        """
        if not self.token or not self.expires_at:
            raise ValueError("Không có remember-token hợp lệ")

        return {
            "version": 1,
            "email": self.email,
            "provider": self.provider,
            "session_token": self.token,
            "expires_at": self.expires_at.isoformat()
        }


def expiry_utc(value):
    """
    Chuẩn hóa thời gian về UTC  
    Ví dụ:  
    `"2026-10-09T08:00:00Z"` được chuyển thành `"2026-10-09T08:00:00+00:00"`
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise BackendUnavailable("Dữ liệu hạn phiên không hợp lệ") from exc

    if not isinstance(value, datetime):
        raise BackendUnavailable("Server chưa trả hạn phiên")

    # Nếu thiếu múi giờ thì giả định múi giờ đó là +7
    if value.tzinfo is None:
        value = value.replace(tzinfo=LEGACY_DB_TIMEZONE)

    return value.astimezone(timezone.utc)


def active(value):
    """
    Kiểm tra trạng thái tài khoản
    """
    # Không dùng truthiness: chuỗi "False" cũng là truthy.
    return value is True or (type(value) is int and value == 1)


def role(value):
    """
    Kiểm tra quyền có giá trị
    """
    if not isinstance(value, str) or not value.strip():
        raise BackendUnavailable("Server chưa trả quyền hợp lệ")
    return value


class DatabaseAuthAdapter:
    """
    Lớp các thực đăng nhập
    """
    def __init__(self, database_factory=None, verifier=None):
        """
        Khởi tạo DB
        """
        self.database_factory = database_factory
        self.verifier = verifier

    @contextmanager
    def _db(self):
        """
        Tạo DB và chuẩn hóa lỗi
        """
        if self.database_factory is None:
            factory = MyDatabase
        else:
            factory = self.database_factory

        db = None
        try:
            db = factory()  # Kết nối được tạo và sử dụng trong cùng worker.
            yield db
        except AuthError:
            raise
        except Exception as exc:
            # Không trả connection string/SQL/password ra UI/log.
            raise BackendUnavailable("Không thể kết nối hoặc xử lý xác thực. Vui lòng thử lại.") from exc

    @staticmethod
    def _rows(result):
        """
        Kiểm tra kết quả trả về
        """
        # Chỉ chấp nhận phản hồi dictionary với success là đúng Boolean True.
        if not isinstance(result, dict) or result.get("success") is not True:
            raise BackendUnavailable("Dịch vụ xác thực tạm thời không khả dụng")

        # Lấy dữ liệu từ DB
        data = result.get("data")
        if data is None:
            return []

        if not isinstance(data, (list, tuple)):
            raise BackendUnavailable("Kết quả xác thực sai định dạng")
        return data

    def _restore(self, db, token, provider):
        """
        Kiểm tra token với DB
        """
        # Lấy thông tin người dùng từ token
        rows = self._rows(db.get_user_by_session(token))
        if not rows:
            raise InvalidSession("Phiên đã hết hạn hoặc bị thu hồi. Hãy đăng nhập lại.")

        if len(rows) != 1 or len(rows[0]) < 6:
            raise BackendUnavailable("Dữ liệu phiên không đúng cấu trúc")

        # User_Name, Email, IsActive, Privilege, Status, ExpiresAt.
        row = rows[0]
        if not active(row[2]):
            raise InvalidSession("Tài khoản không còn được phép đăng nhập")

        # Kiểm tra tài khoản có bị khóa hay không
        expires = expiry_utc(row[5])
        if expires <= datetime.now(timezone.utc):
            raise InvalidSession("Phiên đã hết hạn. Hãy đăng nhập lại.")

        if not isinstance(row[1], str) or not row[1]:
            raise BackendUnavailable("Server chưa trả danh tính hợp lệ")

        return AuthSession(row[1], role(row[3]), provider, token, expires)

    def restore(self, record):
        """
        Đối chiếu thông tin session ở local và DB  
        Token từ file đã giải mã và xác thực lại.
        """
        with self._db() as db:
            session = self._restore(db, record["session_token"], record["provider"])
            if session.email.casefold() != record["email"].casefold():
                raise InvalidSession("Danh tính phiên không khớp; hãy đăng nhập lại")

            return session

    def _remember(self, db, session, remember):
        """
        Tạo token khi người dùng bấm ghi nhớ đăng nhập
        """
        # Nếu không chọn ghi nhớ thì bỏ qua, tiến hành trả dữ liệu để đăng nhập
        if not remember:
            return session

        # Tạo token
        token = None
        try:
            # Tạo thông tin lưu trữ trên DB
            result = db.create_session_by_email(email=session.email, days=REMEMBER_DAYS, device_info="Quan Desktop (" + session.provider + ")")

            # Nếu không được thì báo lỗi
            if not isinstance(result, dict) or result.get("success") is not True:
                raise BackendUnavailable("Không thể tạo phiên ghi nhớ")

            # Lấy dữ liệu token vừa tạo
            token = result.get("token")
            if not isinstance(token, str) or not token or len(token) > 8192:
                raise BackendUnavailable("Token trả về không hợp lệ")

            # Xác nhận phiên vừa cấp, quyền/danh tính và hạn từ DB
            confirmed = self._restore(db, token, session.provider)
            if confirmed.email.casefold() != session.email.casefold(): # So sánh không phân biệt hoa vs thường
                raise InvalidSession("Phiên mới không khớp tài khoản")

            return AuthSession(confirmed.email, confirmed.permission, session.provider,
                               token, confirmed.expires_at, newly_issued=True)
        except Exception: # pylint: disable=broad-except
            if token:
                self._revoke(db, token)
            return AuthSession(session.email, session.permission, session.provider,
                warning="Đăng nhập thành công nhưng chưa thể ghi nhớ. Lần sau cần nhập lại mật khẩu.")

    def password_login(self, email, password, remember):
        """
        Kiểm tra email và mật khẩu
        """
        with self._db() as db:
            rows = self._rows(db.get_password_salt_password_privilege_user(email=email))

            if not rows:
                raise InvalidCredentials("Email hoặc mật khẩu không đúng, hoặc tài khoản chưa được phép đăng nhập")

            if len(rows) != 1 or len(rows[0]) < 5:
                raise BackendUnavailable("Dữ liệu tài khoản không đúng cấu trúc")

            # Lấy dữ liệu và xác thực mật khẩu
            row = rows[0]
            stored_hash = row[0]
            stored_salt = row[1]

            # Khi đăng nhập bằng google/facebook thì 2 trường này Null
            if stored_hash is None or stored_salt is None:
                raise InvalidCredentials(
                    "Email hoặc mật khẩu không đúng, "
                    "hoặc tài khoản chưa hỗ trợ đăng nhập bằng mật khẩu."
                )

            # Nếu truyền vào phương thức xác thực thì sử dụng nó, còn không thì mặc định sử dụng Hash
            verifier = self.verifier
            if verifier is None:
                verifier = Hash.verify

            valid = verifier(stored_salt=stored_salt, stored_hashed_password=stored_hash, input_password=password)

            if not valid or not active(row[2]):
                raise InvalidCredentials("Email hoặc mật khẩu không đúng, hoặc tài khoản chưa được phép đăng nhập")

            session = AuthSession(email, role(row[4]))
            # Cập nhật thông tin đăng nhập mới nhất
            try:
                db.update_last_login_at(email)
            except Exception:  # pylint: disable=broad-except
                pass

            # Tiếp bước xử lý có ghi nhớ thông tin đăng nhập hay không
            return self._remember(db, session, remember)

    def oauth_login(self, provider, info, remember):
        """
        Luồng chung cho đăng nhập bằng Google/Facebook:

        1. Đã liên kết với tài khoản nội bộ + active: đăng nhập.
        2. Chưa mapping + email nội bộ đã tồn tại: yêu cầu liên kết.
        3. Chưa mapping + email chưa tồn tại: tạo User chưa kích hoạt rồi thông báo chờ duyệt.

        info phải đến từ service xác minh provider đáng tin cậy.
        """

        # ---------- Kiểm tra dữ liệu provider ----------
        if provider not in {"google", "facebook"}:
            raise InvalidCredentials("Provider không hỗ trợ")

        if not isinstance(info, dict):
            raise InvalidCredentials("Nhà cung cấp trả dữ liệu không hợp lệ")

        # Google trả về sub, Facebook trả về id
        identifier_key = "sub" if provider == "google" else "id"

        # Thông tin xác thực từ nhà cung cấp
        identifier = info.get(identifier_key)
        email = info.get("email")
        display_name = info.get("name")

        if (not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 255):
            raise InvalidCredentials("Nhà cung cấp chưa trả định danh hợp lệ")

        if (not isinstance(email, str) or not email.strip() or len(email) > 320):
            raise InvalidCredentials(
                "Không nhận được email từ nhà cung cấp. "
                "Hãy sử dụng phương thức đăng nhập khác "
                "hoặc liên hệ quản trị viên."
            )

        email = email.strip()
        if provider == "google" and info.get("email_verified") is not True:
            raise InvalidCredentials("Google chưa xác nhận email này")

        if not isinstance(display_name, str) or not display_name.strip():
            display_name = "Người dùng mới"

        display_name = display_name.strip()[:200]

        # ---------- Database quyết định trạng thái ----------
        # gọi procedure xử lý
        with self._db() as db:
            result = db.resolve_or_register_external_user(
                provider=provider,
                provider_user_id=identifier,
                provider_email=email,
                display_name=display_name,
            )

            rows = self._rows(result)
            if len(rows) != 1 or len(rows[0]) != 7:
                raise BackendUnavailable("Database trả kết quả đăng nhập không đúng cấu trúc")

            # Lấy kết quả trả về
            result_code, internal_email, _internal_name, permission, is_active, stored_provider, stored_identifier = rows[0]

            # internal_name hiện chưa dùng để cấp quyền.
            # Có thể dùng hiển thị nếu AuthSession được mở rộng sau này.
            if result_code == "LINK_REQUIRED":
                raise AccountLinkRequired(
                    "Email này đã có tài khoản nội bộ nhưng chưa liên kết với Google/Facebook. "
                    "Hãy đăng nhập bằng tài khoản nội bộ, sau đó chọn Liên kết tài khoản."
                )

            if result_code == "CREATED_PENDING":
                raise AccountPendingApproval(
                    "Tài khoản đã được tạo với quyền User. Vui lòng chờ quản trị viên kích hoạt trước khi sử dụng phần mềm."
                )

            if result_code == "ACCOUNT_INACTIVE":
                raise AccountInactive(
                    "Tài khoản chưa được kích hoạt hoặc đã bị khóa. Vui lòng liên hệ quản trị viên."
                )

            if result_code != "LOGIN_ALLOWED":
                raise BackendUnavailable("Database trả trạng thái đăng nhập không được hỗ trợ")

            # ---------- Kiểm tra chéo trước khi cấp session ----------
            if (
                not isinstance(stored_provider, str)
                or stored_provider.casefold() != provider
                or not isinstance(stored_identifier, str)
                or stored_identifier != identifier
            ):
                raise InvalidCredentials("Danh tính provider không khớp liên kết nội bộ")

            if (not isinstance(internal_email, str) or not internal_email.strip()):
                raise BackendUnavailable("Database chưa trả email nội bộ hợp lệ")

            if not active(is_active):
                raise AccountInactive("Tài khoản chưa được phép đăng nhập")

            # Tạo Session cho việc ghi nhớ đăng nhập
            session = AuthSession(email=internal_email,permission=role(permission),provider=provider,)

            return self._remember(db, session, bool(remember))

    @staticmethod
    def _revoke(db, token):
        """
        Thu hồi token
        """
        method = getattr(db, "revoke_session", None)
        if not callable(method):
            return False

        # Tiến hành thu hồi trên DB
        try:
            result = method(token)
            return result is True or (isinstance(result, dict) and result.get("success") is True)
        except Exception: # pylint: disable=broad-except
            return False

    def revoke(self, token):
        """
        Thu hồi token
        """
        if not token:
            return True
        try:
            with self._db() as db:
                return self._revoke(db, token)
        except AuthError:
            return False
