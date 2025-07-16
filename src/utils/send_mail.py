import smtplib
from smtplib import SMTPException
import threading
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import re
import datetime
import os


logger = logging.getLogger(__name__)


class InternalEmailSender():
    """
    Gửi email bằng mail ảo  trong nội bộ
    Cần có địa chỉ host SMRT và port của công ty

    Sử dụng mật khẩu ứng dụng (tránh lộ mật khẩu gốc mà vẫn có toàn quyền gửi mail):
    def __init__(self, from_email = "nguyenducquan2001@gmail.com", from_password = "2345678910jqka", email_service='gmail'):
    Sử dụng mật khẩu gốc đăng nhập outlook:
    def __init__(self, from_email = "nguyenducquan2001@outlook.com", from_password = "my_password", email_service='outlook')
    """
    def __init__(self, smtp_host = "10.98.28.206", smtp_port = 25, from_email = "No-Reply@terumo.co.jp", email_service= ''):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.from_email = from_email

        self.email_service = email_service.lower()

        # Cấu hình cho Gmail
        if self.email_service == 'gmail':
            self.smtp_server = 'smtp.gmail.com'
            self.smtp_port = 587
        # Cấu hình cho Outlook
        elif self.email_service == 'outlook':
            self.smtp_server = 'smtp.office365.com'
            self.smtp_port = 587
        else:
            logger.debug("Sử dụng dịch vụ gửi mail nội bộ")
            # raise ValueError("Chỉ hỗ trợ Gmail hoặc Outlook.")

        # Tạo chữ ký mặc định cho email
        self.signature_email = """
                <br><br>
                <p style="color: #000000; font-size: 17px; font-weight: bold; line-height: 1; font-family: Calibri, sans-serif;">Thank and best regards</p>
                <p style="color: #000000; font-size: 17px; font-weight: bold; line-height: 1; font-family: Calibri, sans-serif;">My APP</p>
                <br><br>
            """
    
    def check_email_credentials(self, email, password):
        """
        Kiểm tra địa chỉ email và password được cung cấp có hợp lệ không bằng cách đăng nhập
        """
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()  # Encrypt the connection
                server.login(email, password)  # Try logging in
                # print("Đăng nhập thành công!")
                return True
        except SMTPException as e:
            # print(f"Lỗi khi đăng nhập: {e}")
            return False

    def is_valid_email(self, email):
        """
        Kiểm tra tính hợp lệ của địa chỉ email bằng biểu thức chính quy.
        """
        regex = r'^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$'
        return re.match(regex, email) is not None
    
    def attach_file(self, msg, attachment_path):
        """
        Đính kèm tệp vào email.
        
        :param msg: Đối tượng email.
        :param attachment_path: Đường dẫn tệp đính kèm.
        """
        # Lấy tên tệp từ đường dẫn
        filename = os.path.basename(attachment_path)

        try:
            # Mở tệp và đính kèm vào email
            with open(attachment_path, 'rb') as attachment:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={filename}')
                msg.attach(part)
        except Exception as e:
            logger.error("Không thể đính kèm tệp tin: %s. Lỗi xuất hiện: %s", attachment_path, e)

    def send_email(self, to_email, subject, body, signature='', attachment_path=None, cc_email=None):
        """
        Gửi email với nội dung và tệp đính kèm.
        :param to_email: Địa chỉ email người nhận.
        :param subject: Tiêu đề email.
        :param body: Nội dung email.
        :param signature: Chữ ký email (HTML).
        :param attachment_path: Đường dẫn tệp đính kèm.
        :param cc_email: Địa chỉ email CC (có thể là 1 string hoặc list)
        """
        success_send_email = True

        if not self.is_valid_email(to_email):
            logger.error("Địa chỉ email %s không hợp lệ.", to_email)
            success_send_email = False
            return success_send_email

        try:
            # Tạo đối tượng email
            msg = MIMEMultipart()
            msg['From'] = self.from_email
            msg['To'] = to_email
            msg['Subject'] = subject

            # Nếu có CC
            recipients = [to_email]
            if cc_email:
                if isinstance(cc_email, str):
                    msg['Cc'] = cc_email
                    recipients.append(cc_email)
                elif isinstance(cc_email, list):
                    msg['Cc'] = ', '.join(cc_email)
                    recipients.extend(cc_email)

            # Thêm nội dung email với mã hóa UTF-8
            email_body = body + signature
            msg.attach(MIMEText(email_body, 'html', _charset='utf-8'))

            # Nếu có tệp đính kèm
            if attachment_path:
                self.attach_file(msg, attachment_path)

            # Thiết lập kết nối đến SMTP server nội bộ
            server = smtplib.SMTP(self.smtp_host, self.smtp_port)

            # Gửi email
            server.sendmail(self.from_email, recipients, msg.as_string())

            # Đóng kết nối
            server.quit()

            return success_send_email

        except Exception as e:
            logger.error("Gửi email tới %s thất bại. Lỗi: %s", to_email, e)
            success_send_email = False
            return success_send_email

    def send_email_async(self, to_email, subject, body, signature='', attachment_path=None, callback=None, cc_email=None):
        """
        Gửi email trong một luồng riêng biệt và gọi callback khi hoàn thành.
        Để xác nhận xem email gửi thành công hay không
        """
        def run():
            success = self.send_email(to_email, subject, body, signature, attachment_path, cc_email)

            if callback:
                callback(to_email, success)

            return success
        
        email_thread = threading.Thread(target=run)
        email_thread.start()

    def send_email_for_new_account(self, to_email, name, website_name, attachment_path=None, callback=None):
        """
        Gửi email thông báo tài khoản và mật khẩu đến người dùng tạo mới mật khẩu
        """
        subject_mail = f"Tạo tài khoản mới tại {website_name}"
        body_account_creation = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2 style="color: #007BFF;">Tạo tài khoản thành công!</h2>
                <p>Chào {name},</p>
                <p><strong>{website_name}</strong> thông báo rằng tài khoản của bạn đã được tạo thành công.</p>
                <p>Để có thể truy cập vào <strong>{website_name}<strong/>, hãy liên hệ với nhà phát triển để kích hoạt tài khoản.</p>
                <p></p>
                <p>Đây là mail tự động, vui lòng không phản hồi mail này!</p>
            </body>
        </html>
        """
        # Gửi email với nội dung và chữ ký
        success_send_email = self.send_email_async(to_email = to_email, subject = subject_mail, 
                                             body= body_account_creation, signature = self.signature_email, 
                                             attachment_path = attachment_path, callback= callback)
        
        return success_send_email

    def send_email_for_password_reset(self, to_email, name, website_name, OTP, attachment_path=None, callback= None):
        """
        Gửi email thông báo thay đổi mật khẩu cho người dùng khi quên mật khẩu.
        """
        subject_mail = f"Thay đổi mật khẩu tài khoản tại {website_name}"
        body_password_reset = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <h2 style="color: #b34700;">Mã OTP để thay đổi mật khẩu!</h2>
                <p>Chào {name},</p>
                <p>Chúng tôi muốn thông báo rằng mật khẩu tài khoản của bạn tại <strong>{website_name}</strong> đã được yêu cầu thay đổi.</p>
                <p>Vui lòng sử dụng mã OTP dưới đây để thay đổi mật khẩu tài khoản của bạn:</p>
                <ul>
                    <li><strong>Mã OTP:</strong> {OTP}</li>
                </ul>
                <p>Lưu ý mã OTP chỉ có hiệu lực trong 10 phút!</p>
                <p>Vui lòng thực hiện biện pháp bảo mật tài khoản nếu bạn không phải là người thực hiện thay đổi này.</p>
            </body>
        </html>
        """
        # Gửi email với nội dung và chữ ký
        success_send_email = self.send_email_async(to_email, subject = subject_mail,
                                              body = body_password_reset, signature = self.signature_email,
                                                attachment_path = attachment_path, callback= callback)
        return success_send_email

# Ví dụ sử dụng
if __name__ == "__main__":


    email = InternalEmailSender()
    email.send_email_for_new_account(
                    to_email= "nguyenducquan2001@gmail.com",
                    website_name= "DucQuanApp",
                    name= "Quân"
                )
