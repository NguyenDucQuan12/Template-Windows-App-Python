import schedule  #pip install schedule
import time
import logging
import threading



logger = logging.getLogger(__name__)

class Schedule_Auto:
    """
    Tự động thực hiện một công việc được lập lịch theo thời gian cho trước
    """
    def __init__(self):
        pass
    
    def schedule_daily(self, task, day = None, hour = None, minute = None):
        """
        Lên lịch làm 1 nhiệm vụ vào 1 thời điểm trong ngày, hoặc 1 thời điểm trong tháng
        """
        # Kiểm tra nếu có tham số ngày thì sẽ lập lịch nó theo 1 thời gian hằng tháng
        if day is not None:
            logger.info("Đã lên lịch 1 nhiệm vụ hằng tháng vào %s:%s ngày %s mỗi tháng", hour, minute, day)
            schedule_job = schedule.Scheduler()
            # schedule_job.every(3).seconds.do(task)   # Hàm test theo từng giây
            schedule_job.every().day.at(f"{hour}:{minute}").do(self.check_monthly_task, day=day, task=task)

            # Tạo biến để lưu giá trị dừng lịch trình
            stop_event = threading.Event()

        # Nếu không truyền tham số ngày vào thì thực hiện lập lịch hằng ngày
        else:
            logger.info("Đã lên lịch 1 nhiệm vụ hằng ngày vào thời gian: %s:%s", hour, minute)
            schedule_job = schedule.Scheduler()
            # schedule_job.every(3).seconds.do(task)   # Hàm test theo từng giây
            schedule_job.every().day.at(f"{hour}:{minute}").do(task)  # Hằng ngày tại giờ phút chỉ định

            # Tạo biến để lưu giá trị dừng lịch trình
            stop_event = threading.Event()

        return schedule_job, stop_event
        

    def check_monthly_task(self, day, task):
        """
        Kiểm tra xem hôm nay có phải là ngày đã lên lịch không, nếu có thì thực thi tác vụ
        """
        today = time.localtime()
        logger.debug("Kiểm tra thời gian, local time: %s - time schedule: %s", today, day)
        if today.tm_mday == int(day):
            logger.info(f"Đã đến thời gian được lập lịch ngày {day} hàng tháng.")
            task()  # Thực thi tác vụ

    def check_schedule(self, stop_event: threading.Event, schedule_job: schedule):
        """
        Kiểm tra công việc đã lên lịch mỗi giây để không bỏ qua công việc đã lên lịch
        """
        while not stop_event.is_set():  # Kiểm tra sự kiện dừng
            schedule_job.run_pending()  # Kiểm tra và thực thi công việc
            time.sleep(1)  # Đợi 1 giây trước khi kiểm tra lại

    def start_schedule(self, stop_event: threading.Event, schedule_job: schedule):
        """
        Tạo 1 luồng kiểm tra lịch trình để không gây ảnh hưởng đến giao diện chính
        """
        stop_event.clear()  # Đảm bảo sự kiện dừng không được set
        # Tạo luồng thực thi
        start_schedule_in_thread = threading.Thread(target=self.check_schedule, args=(stop_event, schedule_job))
        start_schedule_in_thread.daemon = True  # Luồng này sẽ tự động kết thúc khi chương trình chính kết thúc
        start_schedule_in_thread.start()
        logger.debug("Luồng kiểm tra lịch trình đã được khởi động.")

        return start_schedule_in_thread
    
    def stop_schedule(self, stop_event: threading.Event, schedule_job: schedule.Scheduler, start_schedule_in_thread: threading.Thread):
        """
        Dừng luồng kiểm tra lịch trình một cách an toàn
        """
        # Hủy lịch trình
        schedule.cancel_job(schedule_job)
        stop_event.set()  # Gửi tín hiệu dừng cho luồng kiểm tra lịch trình

        # Đảm bảo luồng kiểm tra đã dừng
        if start_schedule_in_thread.is_alive():
            start_schedule_in_thread.join()  # Chờ luồng kiểm tra kết thúc
        logger.info("Đã kết thúc lịch trình: %s", schedule_job)

    def restart_schedule(self, task, day=None, hour=None, minute=None, stop_event=None, schedule_job=None, start_schedule_in_thread=None):
        """
        Khởi động lại một quá trình lập lịch với thời gian mới.
        """
        # Dừng lịch hiện tại (nếu có)
        if schedule_job:
            self.stop_schedule(stop_event, schedule_job, start_schedule_in_thread)
        
        # Lên lịch lại tác vụ với thời gian mới
        new_schedule_job, new_stop_event = self.schedule_daily(task, day, hour, minute)
        
        # Khởi động lại kiểm tra lịch trình với thời gian mới
        new_thread = self.start_schedule(new_stop_event, new_schedule_job)
        
        logger.info("Quá trình lập lịch đã được khởi động lại với thời gian mới: %s:%s, %s mỗi tháng" % (hour, minute, day if day else "hằng ngày"))
        
        return new_schedule_job, new_stop_event, new_thread


if __name__ == "__main__":

    """
    Để test thì hãy sử dụng các hàm có lập lịch test theo từng giây để thấy rõ hiệu quả nhất tại schedule_daily
    MẶc định các hàm lập lịch đang thực hiện theo ngày chứ không phải theo từng giây
    """

    # Ví dụ về các tác vụ gửi email
    def send_daily_emails():
        logger.info("Gửi email hằng ngày")
        # Lệnh gửi email hằng ngày

    def send_monthly_emails():
        logger.info("Gửi email hằng tháng")
        # Lệnh gửi email hằng tháng


    active_threads = threading.active_count()
    logger.info(f"Số lượng luồng đang chạy: {active_threads}")
    
    schedule_auto_mail = Schedule_Auto()

    # Lên lịch gửi email hằng ngày vào lúc 11:00 AM
    send_mail_11, mail_stop_event = schedule_auto_mail.schedule_daily(send_daily_emails, hour="11", minute="00")
    start_schedule_in_thread = schedule_auto_mail.start_schedule(stop_event=mail_stop_event, schedule_job=send_mail_11)  # Bắt đầu kiểm tra lịch trình
    time.sleep(15)

    active_threads = threading.active_count()
    logger.info(f"Số lượng luồng đang chạy: {active_threads}")

    # Khởi dộng lại với thời gian mới
    send_mail_11, mail_stop_event, start_schedule_in_thread = schedule_auto_mail.restart_schedule(task= send_daily_emails, hour="12", minute="00", stop_event= mail_stop_event,
                                                                                                  schedule_job= send_mail_11, start_schedule_in_thread= start_schedule_in_thread )
    time.sleep(15)

    active_threads = threading.active_count()
    logger.info(f"Số lượng luồng đang chạy: {active_threads}")


    # Khởi dộng lại với thời gian mới
    send_mail_11, mail_stop_event, start_schedule_in_thread = schedule_auto_mail.restart_schedule(task= send_daily_emails, hour="13", minute="00", stop_event= mail_stop_event,
                                                                                                  schedule_job= send_mail_11, start_schedule_in_thread= start_schedule_in_thread )
    time.sleep(15)

    active_threads = threading.active_count()
    logger.info(f"Số lượng luồng đang chạy: {active_threads}")


    time.sleep(15)
    logger.info("Đã đến thời gian dừng lịch trình.")
    schedule_auto_mail.stop_schedule(stop_event=mail_stop_event, schedule_job=send_mail_11, start_schedule_in_thread=start_schedule_in_thread)

    active_threads = threading.active_count()
    logger.info(f"Số lượng luồng đang chạy: {active_threads}")
    
    time.sleep(15)
    logger.info(f"Chương trình kết thúc. Luồng: {start_schedule_in_thread.is_alive()}")

    active_threads = threading.active_count()
    logger.info(f"Số lượng luồng đang chạy: {active_threads}")