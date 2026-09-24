"""
BENCHMARK NHẬP TRỰC TIẾP — sửa CONFIG rồi bấm Run.
"""
from copy import deepcopy
from types import SimpleNamespace
import getpass
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import json
import math
import os
import sys
from pathlib import Path
import random
import threading
import time
import openpyxl
import pyodbc
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.chart import LineChart, Reference


PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(PROJECT_DIR)
from services.database_service import MyDatabase

# =====================================================================
# Cấu hình tham số
# Giới hạn tối đa 100 capacity/workers là giới hạn của bộ test, không phải giới hạn SQL Server
# Nếu máy server có nhiều người đang dùng, ưu tiên sử dụng bản DB test để bài tạo tải liên tục không ảnh hưởng công việc khác
# =====================================================================
CONFIG = {
    "server": "localhost",                  # VD: r"MAYCHU\SQLEXPRESS"
    "database": "DucQuanApp",               # Nên chọn bản DB thử có dữ liệu thật tương đương
    "user_name": "ducquan_user",            # Thay bằng SQL login có quyền đọc/EXEC
    "password": "123456789",                # Nhập trực tiếp; để rỗng sẽ hỏi khi bấm Run

    "capacities": [4, 6, 8],                # Số giới hạn kết nối tới Database đồng thời (semaphore) để thử nghiệm. Có thể đặt nhiều mức, ví dụ [4, 6, 8] hoặc mỗi 4.
    "workers": None,                        # Là số luồng phát yêu cầu đồng thời. Có nghĩa là có bao nhiêu luồng Python cùng chạy. Nếu luồng nhiều hơn capacity, các luồng sẽ chờ lấy slot semaphore. None nghĩa là workers = capacity.
    "scenario": "list",                     # Là kịch bản tải: ping, list hoặc mixed. Ping chỉ gọi SELECT 1; List gọi list_users_page; Mixed sẽ lấy xác suất 50% gọi list_users_page và 50% gọi get_user_detail
    "pages": [1],                           # Chỉ lấy trang 1; nếu có nhiều trang, hãy thử các trang khác nhau. Nếu page_size=50 và chỉ có 80 người, trang 3 sẽ rỗng. Chọn pages=[1,2] thay vì [1,2,3] để tránh cảnh báo.
    "page_size": 50,                        # Yêu cầu tối đa 50 người dùng trong mỗi trang
    "seconds": 30,                          # Thời gian phát yêu cầu cho MỖI lần đo chính
    "warmup": 5,                            # Chạy làm nóng 5 giây trước khi đo chính, không gộp vào Summary
    "repeats": 3,                           # Số lần lặp của MỖI capacity
    "think_ms": 0,                          # Nghỉ sau mỗi thao tác: 0=tải liên tục; 200=0,2 giây

    "acquire_timeout": 3.0,                 # Thời gian chờ lấy slot semaphore; nếu quá thời gian này, worker sẽ báo lỗi và dừng phát.
    "connect_timeout": 5,                   # Thời gian timeout kết nối ODBC; nếu quá thời gian này, worker sẽ báo lỗi và dừng phát.
    "query_timeout": 15,                    # Thời gian timeout cho mỗi câu SQL; nếu quá thời gian này, worker sẽ báo lỗi và dừng phát.
    "p95_limit_ms": 1000.0,                 # Nếu P95 latency vượt 1.000 ms, benchmark dừng tăng capacity. P95 là giá trị latency mà 95% thao tác thành công nhanh hơn hoặc bằng
    "stop_ms": 10000.0,                     # Nếu một thao tác mất hơn 10 giây, dừng phase.
    "max_samples": 150000,                  # Mỗi phase tối đa 50.000 request để chặn tăng RAM
    "excel_samples": 1000,                  # Chỉ đưa 1.000 mẫu đầu vào Excel để file không quá lớn. CSV vẫn giữ toàn bộ mẫu.

    "trust_server_certificate": True,       # True chỉ khi chủ động bỏ kiểm tra cert môi trường thử
    "monitor": True,                        # True: lấy snapshot server, cần quyền DMV (DMV là các view hệ thống của SQL Server). Nếu monitor_user_name rỗng, dùng cùng SQL login ở trên; nếu monitor_user_name khác, cần nhập monitor_password.
    "monitor_user_name": "",                # Rỗng: monitor dùng cùng SQL login ở trên
    "monitor_password": "",                 # Login monitor riêng mà rỗng password -> hỏi khi Run
    "out": "benchmark_results_direct",      # Thư mục tương đối tính từ vị trí tệp .py này
}

"""
CÁCH CẤU HÌNH ĐỂ CHẠY CÁC THỬ NGHIỆM  
  
A. Lần đầu kiểm tra đường kết nối
"capacities": [1],
"workers": None,
"scenario": "ping",
"seconds": 10,
"warmup": 3,
"repeats": 1,
"monitor": False,

Chạy SELECT 1. Nếu lỗi thì xử lý driver, server, database, tài khoản, mạng hoặc chứng chỉ trước. Ping nhanh chưa chứng minh danh sách/báo cáo cũng nhanh.

B. Kiểm tra màn hình danh sách người dùng
"capacities": [4, 6, 8],
"workers": None,
"scenario": "list",
"pages": [1],
"page_size": 50,
"seconds": 30,
"warmup": 5,
"repeats": 3,
"think_ms": 0

Ở mức 4 có 4 worker, ở mức 6 có 6 worker, mức 8 có 8 worker. Một worker gọi lấy một trang, nhận và xử lý xong rồi gọi lần tiếp.
Mỗi mức đo ba lần; mỗi lần gồm 5 giây làm nóng và 30 giây đo. Khoảng thời gian phát tải tổng cộng là 3 mức × 3 lần × (5+30) = 315 giây.
Thời gian thực chạy còn gồm preflight, chờ truy vấn cuối hoàn tất và ghi báo cáo, hoặc ngắn hơn nếu tự dừng.

Nếu chỉ có 80 người, page_size=50 thì trang 1 và 2 có dữ liệu, trang 3 rỗng. Chọn pages=[1,2]; đừng đặt [1,2,3] rồi bỏ qua cảnh báo.
Lặp cùng trang sẽ hưởng lợi từ cache; nên thử các trang và tham số thật khi có dữ liệu đủ lớn.

C. Có 20 công việc dồn vào nhưng chỉ cho 4 connection
"capacities": [4, 6, 8],
"workers": 20,
"scenario": "list",
"acquire_timeout": 3.0,
"seconds": 30,
"repeats": 3,

Ở mức 4: tối đa 4 worker giữ lượt vào DB, các worker khác có thể chờ. Khi một worker đóng connection thì trả lượt.
CAPACITY_TIMEOUT nghĩa là một yêu cầu chờ quá 3 giây ở Python, chưa gửi SQL. Semaphore không bảo đảm FIFO; tải liên tục có thể làm một số luồng chờ lâu.

So sánh wait_p95_ms, throughput và p95 giữa 4/6/8, rồi đối chiếu server có còn CPU/I/O/memory không. Không tăng capacity chỉ vì thấy có hàng chờ.

D. Tăng từ 12 đến 100
"capacities": [12, 16, 24, 32, 48, 64, 100],
"workers": None,
"scenario": "list",
"p95_limit_ms": 1000.0,
"stop_ms": 10000.0,

Chỉ làm sau khi các mức thấp hơn vẫn ổn. Nếu mức 16 đã báo P95_LIMIT, chương trình dừng trước 24.
Mục tiêu là tìm mức đáp ứng tốt, không phải cố chạy hết 100.

E. Người dùng vừa mở danh sách vừa xem chi tiết
"capacities": [4, 6, 8],
"workers": 12,
"scenario": "mixed",
"pages": [1],
"think_ms": 200,
"seconds": 60,
"repeats": 3,

Mỗi lượt khoảng 50% lấy chi tiết một UserId thử và 50% lấy danh sách. Có khoảng nghỉ 200 ms sau mỗi thao tác.
Mixed hiện tại CHỈ ĐỌC, không đăng ký, xóa, kích hoạt hoặc tạo OTP. Không suy ra khả năng ghi từ bài này.
"""

# Các khóa chứa thông tin đăng nhập sẽ bị loại bỏ khi xuất Excel/JSON. Nếu muốn xuất ra, hãy xóa khỏi CONFIG.
SECRET_KEYS = {"user_name", "password", "monitor_user_name", "monitor_password"}

def validate_config(settings):
    """
    Kiểm tra cấu hình trước khi chạy benchmark.
    Nếu có lỗi, ném ValueError với thông báo chi tiết.
    """
    # Kiểm tra mọi khóa trong CONFIG có trong settings; nếu thiếu, ném lỗi.
    for key in CONFIG:
        if key not in settings:
            raise ValueError(f"Thiếu cấu hình: {key}")

    # Kiểm tra kiểu dữ liệu và giá trị hợp lệ cho từng khóa.
    for key in ("capacities", "pages"):
        values = settings[key]

        if not isinstance(values, (list, tuple)) or not values:
            raise ValueError(f"{key} phải là list không rỗng, ví dụ [4, 6, 8]")

        if any(type(v) is not int or v < 1 for v in values):
            raise ValueError(f"{key} chỉ chứa số nguyên dương")

        if len(set(values)) != len(values):
            raise ValueError(f"{key} không được lặp phần tử")

    if max(settings['capacities']) > 100:
        raise ValueError('capacities tối đa 100 trong bộ test này')

    if settings['workers'] is not None and (type(settings['workers']) is not int or not 1 <= settings['workers'] <= 100):
        raise ValueError('workers phải là None hoặc số nguyên 1..100')

    for key in ('page_size','seconds','warmup','repeats','connect_timeout','query_timeout','max_samples'):
        if type(settings[key]) is not int or settings[key] < 1:
            raise ValueError(f'{key} phải là số nguyên dương')

    if settings['page_size'] > 200:
        raise ValueError('page_size tối đa 200')

    for key in ('think_ms','excel_samples'):
        if type(settings[key]) is not int or settings[key] < 0:
            raise ValueError(f'{key} phải là số nguyên >=0')

    for key in ('acquire_timeout','p95_limit_ms','stop_ms'):
        value = settings[key]
        if type(value) not in (int,float) or not math.isfinite(value) or value <= 0:
            raise ValueError(f'{key} phải là số hữu hạn >0')

    for key in ('trust_server_certificate','monitor'):
        if type(settings[key]) is not bool:
            raise ValueError(f'{key} phải là True hoặc False')

    if settings['scenario'] not in ('ping','list','mixed'):
        raise ValueError('scenario phải là ping, list hoặc mixed')

    for key in ('server','database','user_name','out'):
        if not isinstance(settings[key], str) or not settings[key].strip():
            raise ValueError(f'{key} phải là chuỗi không rỗng')

    for key in ('password','monitor_user_name','monitor_password'):
        if not isinstance(settings[key], str):
            raise ValueError(f'{key} phải là chuỗi; để trống dùng ""')


def public_config(settings):
    """
    Trả về dict chứa các khóa không nhạy cảm để xuất ra Excel/JSON.
    """
    return {key: value for key,value in settings.items() if key not in SECRET_KEYS}


def percentile(values, p):
    """
    Tính percentiles P50, P95 hoặc P99.  
    Values là danh sách các giá trị thực thi (latency_ms) của các thao tác thành công.  
    Nghĩa là 50%, 95% và 99% request có thời gian thực thi nhỏ hơn hoặc bằng giá trị p.  
    Ví dụ `values = [10, 20, 30, 40]`  
    P50 = 20, có nghĩa là 50% request nhanh hơn hoặc bằng 20.
    P95 = 40, có nghĩa là 95% request nhanh hơn hoặc bằng 40.
    P99 = 40, có nghĩa là 99% request nhanh hơn hoặc bằng 40.
    """
    # Lọc giá trị thiếu rồi sắp xếp: values = [10, None, 30, 20, None] -> [10, 20, 30].
    values = sorted(v for v in values if v is not None)

    # Nearest-rank: với 100 mẫu, p95 là mẫu thứ 95 sau sắp xếp.
    # math.ceil(len(values) * p / 100) - 1 Là tính vị trí phần tử theo cách nearest-rank (1-based index) rồi trừ đi 1 vì Python bắt đầu bằng 0.
    # Với values = [10, 20, 30, 40]
    # p=95, len(values)=4, vị trí = ceil(4*95/100)-1 = ceil(3.8)-1 = 4-1=3
    # trả về values[3]=40.
    return values[max(0, math.ceil(len(values) * p / 100) - 1)] if values else None


def utc_now():
    """
    Trả về thời gian hiện tại theo chuẩn UTC, ISO 8601, có mili giây.  
    Ví dụ: `2026-09-22T09:01:13.028+00:00`
    """
    # UTC giúp đối chiếu nhiều máy; giờ Việt Nam = UTC+7.
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def measure_phase(db, operation, capacity, workers, seconds, repeat,
                  phase, max_samples, think_ms, stop_ms):
    """
    Thực hiện một phase đo với các tham số đã cho.  
    Trả về (summary, samples)
    - summary: dict tóm tắt kết quả, bao gồm capacity, workers, repeat, phase, started_utc, elapsed_s, attempts, successes, errors, error_rate, success_ops_s, status, rows_total, latency_p50_ms, latency_p95_ms, latency_p99_ms, latency_max_ms, wait_p95_ms, connect_p95_ms, work_p95_ms, lease_p95_ms.
    - samples: danh sách mẫu chi tiết, mỗi mẫu là dict chứa thông tin về một lần gọi operation, bao gồm capacity, workers, repeat, phase, worker, started_utc, operation, rows, success, code, sqlstate, native_code, latency_ms, db_calls, wait_ms, connect_ms, work_ms, cleanup_ms, lease_ms, cleanup_failed, error_stage_type.
    Ví dụ:  
    ```python
    summary, samples = measure_phase(
        db=db,
        operation=operation,
        capacity=2,
        workers=5,
        seconds=10,
        repeat=1,
        phase="measure",
        max_samples=1000,
        think_ms=100,
        stop_ms=5000
    )
    ```
    Dùng 5 luồng để làm công việc trong khoảng 10 giây.
    Đối tượng cơ sở dữ liệu đã được cấu hình tối đa 2 lượt sử dụng đồng thời.
    Mỗi luồng nghỉ 100 mili giây sau một thao tác.
    Không phát quá 1.000 lượt.
    Nếu một thao tác trả về sau hơn 5 giây, báo dừng phát thêm công việc.
    """
    # Tạo threading.Event để báo dừng cho các worker. Thông qua stop.set() để báo dừng, stop.is_set() để kiểm tra.
    stop = threading.Event()
    # Tạo khóa để bảo vệ truy cập vào state và samples. Khi một worker đang thay đổi state hoặc samples, các worker khác sẽ chờ lock.
    lock = threading.Lock()

    # state chứa thông tin trạng thái chung giữa các worker và luồng chính. 'reason' là lý do dừng, 'issued' là số yêu cầu đã phát.
    state = {'reason': '', 'issued': 0}
    # Danh sách mẫu kết quả từ các worker. Mỗi mẫu là dict chứa thông tin về một lần gọi operation.
    samples = []

    def open_gate():
        """
        Ghi thời gian bắt đầu và deadline vào state  
        Điều này giúp thời gian tạo thread không bị tính vào kết quả
        """
        # Ghi mốc thời gian bắt đầu đo và thời gian UTC hiện tại vào state và tính mốc thời gian kết thúc (deadline) dựa trên số giây đã cho.
        state['start'] = time.perf_counter()
        state['started_utc'] = utc_now()
        state['deadline'] = state['start'] + seconds

    # Barrier để đồng bộ các worker và luồng chính. Khi tất cả worker và luồng chính gọi gate.wait(), barrier action open_gate() sẽ được gọi.
    # Ví dụ có 4 worker và 1 luồng điều phối chính, barrier sẽ chặn cho đến khi cả 5 gọi gate.wait(). Khi cả 5 đã sẵn sàng, open_gate() chạy và các worker được tiếp tục.
    # Cách này tránh việc worker 1 chạy trước trong khi worker 4 còn đang được khởi tạo.
    gate = threading.Barrier(workers + 1, action=open_gate)

    def worker(worker_id):
        """
        Mỗi worker chạy trong một luồng riêng. worker_id là số thứ tự của worker, từ 0 đến workers-1.  
        Mô phỏng cho 1 luồng người dùng gọi operation liên tục trong thời gian đo.  
        """
        # Sinh bộ random riêng cho mỗi worker để tránh xung đột. Dùng seed = 2026 + worker_id để đảm bảo kết quả có thể tái lập.  
        # ví dụ worker 0 có seed 2026 thì rng sẽ sinh ra cùng một chuỗi số ngẫu nhiên mỗi lần chạy
        rng = random.Random(2026 + worker_id)
        # Nơi lưu kết quả của worker này. Cuối cùng sẽ trả về danh sách chung samples. Mỗi worker có danh sách riêng để tránh xung đột khi ghi vào samples.
        local = []
        # Báo worker này đã sẵn sàng và chờ các worker khác sẵn sàng.
        gate.wait()

        # Worker tiếp tục chạy khi chưa có tín hiệu dừng và chưa hết thời gian.
        while not stop.is_set() and time.perf_counter() < state['deadline']:
            # Lock để bảo vệ truy cập vào state. Khi một worker đang thay đổi state, các worker khác sẽ chờ lock.
            with lock:
                # Kiểm tra đã đạt đến số lượng mẫu tối đa, worker sẽ báo dừng và ghi lý do dừng là 'SAMPLE_CAP'.
                if state['issued'] >= max_samples:
                    if not state['reason']:
                        state['reason'] = 'SAMPLE_CAP'
                    stop.set()
                    break

                # Tăng bộ đếm phát yêu cầu. Mỗi worker tăng 1 cho mỗi lần gọi operation.
                state['issued'] += 1

            # Bắt đâu đo thời gian cho thao tác.
            t0 = time.perf_counter()
            # Tạo 1 bản ghi mẫu kết quả với thông tin về capacity, workers, repeat, phase, worker_id và thời gian bắt đầu.
            row = dict(capacity=capacity, workers=workers, repeat=repeat,
                       phase=phase, worker=worker_id, started_utc=utc_now())

            # Bắt đầu đo thời gian cho thao tác. db.begin_db_measurement() sẽ ghi lại thời gian bắt đầu và các thông tin liên quan đến thao tác.
            db.begin_db_measurement()
            result = {}
            try:
                # Gọi operation với bộ random riêng của worker. operation trả về (tên thao tác, dict kết quả, số dòng trả về).
                # rng.choice(ids) sẽ chọn ngẫ nhiên một id từ danh sách ids. rng.random() sẽ sinh ra số thực ngẫu nhiên trong khoảng [0,1).
                name, result, count = operation(rng)

                # Cập nhật thông tin vào row. Nếu result là None hoặc không có các khóa success, code, sqlstate, native_code, sẽ ghi None.
                row.update(operation=name, rows=count,
                           # chỉ ghi success, code, sqlstate, native_code khi mà result trả về dict có các khóa này. Nếu result là None hoặc không có các khóa này, sẽ ghi None.
                           success=result.get('success') is True,   # success là True nếu thao tác thành công, False nếu thất bại.
                           code=str(result.get('code', 'UNKNOWN')), # code là mã lỗi hoặc thông báo kết quả, ví dụ 'OK', 'TIMEOUT', 'ERROR'.
                           sqlstate=result.get('sqlstate'),         # sqlstate là mã trạng thái SQL chuẩn, ví dụ '00000' cho thành công, 'HYT00' cho timeout.
                           native_code=result.get('native_code'))   # native_code là mã lỗi gốc từ SQL Server, ví dụ 0 cho thành công, 1205 cho deadlock.

            except Exception as exc: # pylint: disable=broad-except
                row.update(operation='exception', rows=0, success=False,
                           code=type(exc).__name__, sqlstate=None, native_code=None)
            finally:
                # Kết thúc đo thời gian cho thao tác operation. db.end_db_measurement() sẽ trả về danh sách các span (khoảng thời gian) của thao tác, ví dụ {'wait_ms': 10, 'connect_ms': 20, 'work_ms': 30, 'cleanup_ms': 5, 'lease_ms': 65}.
                spans = db.end_db_measurement()

            # Ghi lại thông tin về thời gian thực hiện thao tác, số lần gọi DB, các khoảng thời gian chi tiết và trạng thái lỗi.
            row['latency_ms'] = (time.perf_counter() - t0) * 1000  # chuyển từ giây sang mili giây

            # Đếm số lần gọi DB trong spans. Mỗi span là một lần gọi DB, ví dụ một thao tác list có thể gọi nhiều câu SQL.
            row['db_calls'] = len(spans)

            # Gộp các khoảng thời gian từ spans. Nếu spans có nhiều span, sẽ tính tổng các khoảng thời gian wait_ms, connect_ms, work_ms, cleanup_ms, lease_ms. Nếu spans rỗng hoặc không có khóa nào, sẽ ghi None.
            # vì 1 thao tác có thể gọi nhiều câu SQL, mỗi câu SQL có thể có wait_ms, connect_ms, work_ms, cleanup_ms, lease_ms khác nhau. Gộp lại để biết tổng thời gian cho thao tác.
            for key in ('wait_ms', 'connect_ms', 'work_ms', 'cleanup_ms', 'lease_ms'):
                # Lấy các giá trị của key từ spans mà có giá trị không None. Nếu không có giá trị nào, numbers sẽ là danh sách rỗng.
                numbers = [s[key] for s in spans if s.get(key) is not None]
                row[key] = sum(numbers) if numbers else None

            # Gộp thông tin lỗi từ spans. Nếu bất kỳ span nào có cleanup_failed=True, thì row['cleanup_failed'] sẽ là True. Nếu tất cả span đều không có cleanup_failed, thì row['cleanup_failed'] sẽ là False.
            row['cleanup_failed'] = any(s.get('cleanup_failed') for s in spans)
            # Gộp các loại lỗi từ spans. Nếu bất kỳ span nào có error_type, sẽ gộp tất cả các error_type thành một chuỗi phân tách bằng dấu chấm phẩy. Nếu không có lỗi nào, sẽ ghi rỗng.
            row['error_stage_type'] = ';'.join(sorted({s['error_type'] for s in spans if s['error_type']}))

            # Thêm mẫu kết quả của worker vào danh sách local. Cuối cùng, worker sẽ trả về danh sách local cho luồng chính.
            local.append(row)

            # Kiểm tra xem có lỗi nào xảy ra không. Nếu có, dừng lại và ghi lý do.
            if not row['success'] or row['cleanup_failed'] or row['latency_ms'] > stop_ms:
                with lock:
                    if not state['reason']:
                        state['reason'] = 'ERROR' if not row['success'] or row['cleanup_failed'] else 'SLOW_OPERATION'

                # Thông báo cho các luồng khác ngừng bắt đầu vòng làm việc tiếp theo. Dùng stop.set() để báo dừng cho các worker khác.
                stop.set()

            # Nếu think_ms > 0, worker sẽ nghỉ một khoảng thời gian trước khi phát yêu cầu tiếp theo. Điều này giúp giảm tải cho server và mô phỏng hành vi người dùng thực tế.
            if think_ms:
                stop.wait(think_ms / 1000)
        # Khi worker kết thúc vòng lặp, trả về danh sách local chứa các mẫu kết quả của worker này. Luồng chính sẽ thu thập tất cả các mẫu từ các worker.
        return local

    # Tiến hành đo với ThreadPoolExecutor để chạy các worker đồng thời. Mỗi worker sẽ chạy hàm worker(worker_id) trong một luồng riêng.
    with ThreadPoolExecutor(max_workers=workers) as executor:
        # Tạo danh sách các Future đại diện cho các worker. Mỗi worker được submit vào executor và sẽ chạy hàm worker(worker_id). worker_id là số thứ tự của worker, từ 0 đến workers-1.
        futures = [executor.submit(worker, i) for i in range(workers)]
        # Chờ tất cả worker sẵn sàng và mở cổng để bắt đầu đo. Khi tất cả worker gọi gate.wait(), barrier action open_gate() sẽ được gọi và các worker sẽ tiếp tục.
        gate.wait()
        # Ghi thời gian bắt đầu và thời gian UTC khi bắt đầu đo. Thời gian này sẽ được dùng để tính elapsed time và ghi vào kết quả cuối cùng.
        start = state['start']
        started_utc = state['started_utc']
        try:
            # Chờ tất cả worker hoàn thành và thu thập kết quả từ các Future. Khi một worker hoàn thành, future.result() sẽ trả về danh sách mẫu của worker đó. Gộp tất cả mẫu từ các worker vào danh sách samples.
            for future in futures:
                samples.extend(future.result())
        except KeyboardInterrupt:
            # Nếu người dùng nhấn Ctrl+C, sẽ báo dừng và ghi lý do là 'INTERRUPTED'.
            state['reason'] = 'INTERRUPTED'
            stop.set()

            # Xóa danh sách đã gom một phần rồi gom lại đầy đủ để tránh đếm trùng.
            samples = []
            for future in futures:
                samples.extend(future.result())

        # Tính thời gian elapsed từ khi bắt đầu đo đến khi tất cả worker hoàn thành. Thời gian này sẽ được ghi vào kết quả cuối cùng.
        elapsed = time.perf_counter() - start

    # Lấy những thao tác thành công, đồng thời không lỗi dọn tài nguyên.
    ok = [s for s in samples if s['success'] and not s['cleanup_failed']]

    # Gộp kết quả cuối cùng vào dict result.
    result = dict(capacity=capacity, workers=workers, repeat=repeat, phase=phase,
                  started_utc=started_utc, elapsed_s=elapsed, attempts=len(samples),
                  successes=len(ok), errors=len(samples)-len(ok),
                  error_rate=(len(samples)-len(ok))/len(samples) if samples else None,
                  success_ops_s=len(ok)/elapsed, status=state['reason'] or 'COMPLETE',
                  rows_total=sum(s['rows'] for s in ok)) # Tổng số dòng trả về, kể cả khi cùng một người dùng được lấy lặp lại nhiều lần.

    # Không trộn latency lỗi nhanh vào latency thành công.
    for p in (50, 95, 99):
        # Tính percentile p của latency thành công. Nếu không có mẫu thành công, sẽ trả về None.
        result[f'latency_p{p}_ms'] = percentile([s['latency_ms'] for s in ok], p)

    # Tính latency tối đa của tất cả mẫu, kể cả lỗi. Nếu không có mẫu nào, sẽ trả về None.
    result['latency_max_ms'] = max((s['latency_ms'] for s in samples), default=None)
    # Tính p95 của các khoảng thời gian wait_ms, connect_ms, work_ms, lease_ms từ các mẫu thành công. Nếu không có mẫu thành công, sẽ trả về None.
    for key in ('wait_ms','connect_ms','work_ms','lease_ms'):
        result[key.replace('_ms','_p95_ms')] = percentile([s[key] for s in ok], 95)

    return result, samples


# Câu lệnh SQL để lấy thông tin về các session và request đang chạy trên SQL Server. Chỉ lấy các session của người dùng với chương trình DucQuanApp.Benchmark, cùng host_process_id và host_name hiện tại.
# Trả về các cột như session_id, request_id, status, elapsed time, cpu time, logical reads, waits, blocking session id, open transaction count và sql_handle.

# programe_name = 'DucQuanApp.Benchmark' có nghĩa là tên chương trình được truyền vào khi thiết lập kết nối ODBC.
# Ví dụ: self.connection_string = f'DRIVER={driver};SERVER={server};DATABASE={database};UID={user_name};PWD={password};APP=DucQuanApp.Benchmark;TrustServerCertificate=Yes'
REQUEST_SQL = """
SELECT SYSUTCDATETIME() AS sample_utc, s.session_id, r.request_id,
       s.status AS session_status, r.status AS request_status,
       r.total_elapsed_time AS elapsed_ms, r.cpu_time AS cpu_ms,
       r.logical_reads, r.reads, r.writes, r.wait_type, r.wait_time AS wait_ms,
       r.wait_resource, r.blocking_session_id, s.open_transaction_count,
       CONVERT(varchar(130),r.sql_handle,1) AS sql_handle
FROM sys.dm_exec_sessions s
LEFT JOIN sys.dm_exec_requests r ON s.session_id=r.session_id
WHERE s.is_user_process=1 AND s.program_name=N'DucQuanApp.Benchmark'
  AND s.host_process_id=? AND s.host_name=HOST_NAME();
"""


class Monitor:
    """
    Một connection riêng ngoài semaphore, lấy mẫu 1 giây/lần.
    Không lưu SQL text hay dữ liệu người dùng. Không quan sát được request rất ngắn.
    Không có quyền -> ghi Diagnostics; tuyệt đối không coi là server không có tải.
    """
    def __init__(self, db, enabled):
        self.db, self.enabled = db, enabled
        self.samples, self.diagnostics = [], []
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.label = ''

    def run(self):
        """
        Lấy mẫu server DMV mỗi giây. Nếu không có quyền, ghi Diagnostics.
        """
        conn = cursor = None
        try:
            conn = self.db._connect(autocommit=True)  # Cố ý một connection giám sát riêng.
            conn.timeout = 5
            cursor = conn.cursor()
            cursor.execute("""SELECT CASE WHEN CONVERT(int,SERVERPROPERTY('ProductMajorVersion'))>=16
                THEN HAS_PERMS_BY_NAME(NULL,NULL,'VIEW SERVER PERFORMANCE STATE')
                ELSE HAS_PERMS_BY_NAME(NULL,NULL,'VIEW SERVER STATE') END""")
            if cursor.fetchone()[0] != 1:
                raise PermissionError('Monitor requires server DMV permission')
            while not self.stop.is_set():
                label = self.label
                cursor.execute(REQUEST_SQL, os.getpid())
                cols = [c[0] for c in cursor.description]
                rows = [dict(zip(cols, tuple(r)), phase_label=label) for r in cursor.fetchall()]
                with self.lock:
                    self.samples.extend(rows)
                self.stop.wait(1)
        except Exception as exc:
            with self.lock:
                self.diagnostics.append(dict(time_utc=utc_now(), component='monitor',
                                             code=type(exc).__name__,
                                             sqlstate=str(exc.args[0])[:5] if exc.args else ''))
        finally:
            for obj in (cursor, conn):
                if obj is not None:
                    try: obj.close()
                    except Exception: pass

    def start(self):
        """
        Bắt đầu luồng giám sát nếu enabled. Nếu không, thread là None.
        """
        self.thread = threading.Thread(target=self.run, daemon=True) if self.enabled else None
        if self.thread: self.thread.start()

    def snapshot(self):
        """
        Trả về snapshot hiện tại của các mẫu và diagnostics. Sao chép danh sách để tránh thay đổi trong khi đọc.
        """
        with self.lock:
            return list(self.samples), list(self.diagnostics)

    def close(self):
        """
        Dừng luồng giám sát và chờ kết thúc. Nếu không có thread, không làm gì.
        """
        self.stop.set()
        if self.thread: self.thread.join()


def write_csv(path, rows):
    """
    Ghi dữ liệu vào file CSV.
    """
    if not rows: return
    # Lấy mọi tên cột theo thứ tự xuất hiện; BOM giúp Excel đọc đúng tiếng Việt.
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def export_excel(path, sheets):
    """
    Ghi dữ liệu vào file Excel. Mỗi key trong sheets là tên sheet, value là danh sách dict mẫu.
    """
    wb = Workbook()
    wb.remove(wb.active)
    for title, rows in sheets.items():
        ws = wb.create_sheet(title)
        if not rows:
            ws.append(['Thông tin'])
            ws.append(['Không có dữ liệu; xem Diagnostics/Config.'])
        else:
            keys = list(dict.fromkeys(k for row in rows for k in row))
            ws.append(keys)
            for row in rows:
                cells = []
                for key in keys:
                    value = row.get(key)
                    if isinstance(value, datetime):
                        value = value.isoformat()  # thời gian ghi rõ UTC trong tên cột
                    elif isinstance(value, (dict,list,tuple)):
                        value = json.dumps(value, ensure_ascii=False)
                    if isinstance(value, str) and value.startswith(('=', '+', '-', '@')):
                        value = "'" + value  # không cho chuỗi log trở thành công thức Excel
                    cells.append(value)
                ws.append(cells)
            for j, key in enumerate(keys, 1):
                if key == 'error_rate': fmt = '0.00%'
                elif key.endswith(('_ms','_s')): fmt = '#,##0.00'
                else: continue
                for col in ws.iter_cols(min_col=j, max_col=j, min_row=2):
                    for cell in col: cell.number_format = fmt
        ws.freeze_panes = 'A2'
        ws.auto_filter.ref = ws.dimensions
        ws.row_dimensions[1].height = 42
        for cell in ws[1]:
            cell.fill = PatternFill('solid', fgColor='17365D')
            cell.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
            cell.alignment = Alignment(wrap_text=True, vertical='center')
            ws.column_dimensions[cell.column_letter].width = min(44, max(18, len(str(cell.value))+2))
    ws = wb['Summary']
    if ws.max_row > 1 and ws.cell(1,1).value != 'Thông tin':
        names = [c.value for c in ws[1]]
        # Các điểm là từng lần lặp theo thứ tự thực hiện, không phải phép gộp p95.
        for metric, anchor, label in [('success_ops_s','A{}'.format(ws.max_row+4),'Thao tác thành công/giây'),
                                     ('latency_p95_ms','K{}'.format(ws.max_row+4),'p95 thành công (ms)')]:
            chart = LineChart()
            chart.title = label
            chart.add_data(Reference(ws,min_col=names.index(metric)+1,min_row=1,max_row=ws.max_row),titles_from_data=True)
            chart.set_categories(Reference(ws,min_col=names.index('capacity')+1,min_row=2,max_row=ws.max_row))
            chart.x_axis.title = 'Giới hạn kết nối (lặp theo từng lần thử)'
            chart.height, chart.width = 9, 18
            ws.add_chart(chart,anchor)
    temp = path.with_name(path.stem+'.tmp.xlsx')
    wb.save(temp)
    os.replace(temp,path)


METRICS = [
 ('capacity','Số lượt tối đa được phép cùng truy cập cơ sở dữ liệu trong một thời điểm. Đây là giới hạn của bài đo, không phải số kết nối thật của máy chủ.'),
 ('workers','Số luồng cùng phát yêu cầu. Mỗi luồng xử lý một yêu cầu tại một thời điểm.'),
 ('success_ops_s','Số thao tác thành công trung bình trong một giây, tính cả thời gian chờ các thao tác cuối hoàn tất. Đây không phải số câu lệnh SQL trong một giây.'),
 ('latency_p95_ms','Mốc thời gian mà ít nhất 95% thao tác thành công hoàn tất không lâu hơn. Bao gồm thời gian chờ lượt, kết nối, nhận dữ liệu và xử lý trong Python.'),
 ('latency_p99_ms','Mốc thời gian mà ít nhất 99% thao tác thành công hoàn tất không lâu hơn. Cần nhiều mẫu mới đáng tin cậy; vài chục mẫu chưa đủ để kết luận.'),
 ('wait_p95_ms','Mốc thời gian chờ lấy lượt truy cập cơ sở dữ liệu của ít nhất 95% thao tác thành công. Đây không phải thời gian chờ khóa trong SQL Server.'),
 ('connect_p95_ms','Mốc thời gian thực hiện bước kết nối của ít nhất 95% thao tác thành công. Có thể chương trình lấy lại kết nối có sẵn, nên không đồng nghĩa với mở kết nối mới.'),
 ('work_p95_ms','Mốc thời gian thực hiện phần việc chính của ít nhất 95% thao tác thành công: chuẩn bị, chạy câu lệnh, nhận dữ liệu, xử lý Python và hoàn tất giao dịch. Đây không phải riêng thời gian CPU của SQL Server.'),
 ('lease_p95_ms','Mốc thời gian một thao tác thành công giữ lượt truy cập cơ sở dữ liệu, gồm kết nối, thực hiện công việc và dọn dẹp. Không cộng các chỉ số P95 với nhau để suy ra tổng thời gian.'),
 ('rows_total','Tổng số dòng dữ liệu nghiệp vụ mà các thao tác thành công trả về. Dùng để kiểm tra bài đo có thực sự lấy được dữ liệu hay không.'),
 ('error_rate','Tỷ lệ thao tác thất bại hoặc dọn dẹp tài nguyên bị lỗi trên tổng số lần gọi. Chương trình không tự gọi lại khi lỗi.'),
 ('status','Kết quả đánh giá của phía chương trình đo. PASS chỉ có nghĩa là bài đo đạt điều kiện đã đặt ra, không khẳng định toàn bộ máy chủ hoạt động tối ưu.'),
 ('ServerRequests','Ảnh chụp các yêu cầu đang chạy trên máy chủ, được lấy khoảng một giây một lần. Không cộng thời gian hoặc CPU giữa các ảnh chụp vì một yêu cầu có thể xuất hiện nhiều lần.'),
 ('RawSample','Một phần mẫu chi tiết, tối đa N bản ghi đầu tiên của mỗi giai đoạn, dùng để kiểm tra và tìm lỗi. Đây không phải mẫu đại diện ngẫu nhiên; tệp CSV vẫn giữ toàn bộ mẫu.'),
]

def run_benchmark(settings, operation_factory=None):
    """
    Chạy kiểm thử và xuất kết quả.

    settings:
        Dictionary chứa cấu hình.

    operation_factory:
        Không truyền:
            Dùng các lựa chọn có sẵn: ping, list, mixed.

        Có truyền:
            Dùng hàm do bạn cung cấp để tạo thao tác kiểm thử.
            Nhờ đó có thể thử bảng, truy vấn hoặc database khác.

        Hàm này phải nhận:
            operation_factory(db, config)

        Và trả về một hàm:
            operation(rng)

        Mỗi lần operation(rng) chạy phải trả về:
            (tên_thao_tác, dictionary_kết_quả, số_dòng)
    """

    # Tạo bản sao để việc bổ sung mật khẩu không sửa CONFIG ban đầu.
    settings = deepcopy(settings)
    # Kiểm tra cấu hình trước khi tạo tải lên cơ sở dữ liệu.
    validate_config(settings)

    # Nếu chưa nhập mật khẩu trong CONFIG thì hỏi qua terminal.
    if not settings["password"]:
        settings["password"] = getpass.getpass("Mật khẩu SQL Server: ")

    # Không tiếp tục khi mật khẩu vẫn rỗng.
    if not settings["password"]:
        raise ValueError("Chưa nhập mật khẩu SQL Server")

    # Chỉ hỏi mật khẩu giám sát khi bật giám sát và dùng tài khoản riêng.
    if (settings["monitor"] and settings["monitor_user_name"] and not settings["monitor_password"]):
        settings["monitor_password"] = getpass.getpass("Mật khẩu tài khoản giám sát: ")

        # Tài khoản giám sát riêng phải có mật khẩu.
        if not settings["monitor_password"]:
            raise ValueError("Chưa nhập mật khẩu tài khoản giám sát")

    # Cho phép viết config.server thay vì settings["server"].
    config = SimpleNamespace(**settings)
    # Sao chép danh sách các mức giới hạn đồng thời cần thử.
    capacities = list(config.capacities)
    # Sao chép danh sách trang dùng cho bài thử người dùng có sẵn.
    pages = list(config.pages)

    # Chuyển thư mục đầu ra thành đối tượng đường dẫn.
    output_root = Path(config.out).expanduser()
    # Nếu đường dẫn tương đối, đặt nó cạnh tệp Python đang chạy.
    if not output_root.is_absolute():
        output_root = (Path(__file__).resolve().parent / output_root)

    # Đặt tên thư mục riêng theo thời gian UTC của lần chạy.
    folder_name = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f_UTC")
    # Ghép thư mục gốc với tên thư mục của lần chạy này.
    output_directory = output_root / folder_name
    # Tạo thư mục; báo lỗi nếu tên này đã tồn tại.
    output_directory.mkdir(parents=True, exist_ok=False)

    def make_database(capacity, for_monitor=False):
        """Tạo đối tượng truy cập cơ sở dữ liệu."""

        # Chỉ dùng tài khoản riêng khi đây là đối tượng giám sát.
        use_monitor_account = (for_monitor and bool(config.monitor_user_name))
        # Chọn tên đăng nhập phù hợp với mục đích của đối tượng.
        username = (config.monitor_user_name if use_monitor_account else config.user_name)
        # Chọn mật khẩu đi cùng tên đăng nhập.
        password = (config.monitor_password if use_monitor_account else config.password)

        # Tạo đối tượng DB có giới hạn semaphore tương ứng.
        return MyDatabase(
            server_name=config.server,
            database_name=config.database,
            user_name=username,
            password=password,
            max_concurrent_connections=capacity,
            acquire_timeout=config.acquire_timeout,
            connect_timeout=config.connect_timeout,
            query_timeout=config.query_timeout,
            trust_server_certificate=(
                config.trust_server_certificate
            ),
        )

    # Xác định câu truy vấn thử dùng lựa chọn có sẵn hay thao tác riêng.
    operation_source = "Thao tác tự chọn" if operation_factory is not None else f"Lựa chọn có sẵn: {config.scenario}"

    # Chỉ đưa cấu hình đã loại thông tin đăng nhập vào báo cáo.
    report_config = [
        {"setting": key, "value": value}
        for key, value in public_config(settings).items()
    ]

    # Bổ sung thông tin giúp nhận biết và đối chiếu lần chạy.
    report_config.extend([
        {
            "setting": "started_utc",
            "value": utc_now(),
        },
        {
            "setting": "client_pid",
            "value": os.getpid(),
        },
        {
            "setting": "operation_source",
            "value": operation_source,
        },
        {
            "setting": "method",
            "value": "Mỗi luồng chờ thao tác trước hoàn tất; làm nóng trước khi đo; hàm kiểm thử không tự gọi lại thao tác lỗi",
        },
        {
            "setting": "versions",
            "value": f"pyodbc={pyodbc.version}; openpyxl={openpyxl.__version__}",
        },
    ])

    # Lưu bảng tổng hợp của các giai đoạn đo chính.
    summaries = []
    # Lưu bảng tổng hợp của các giai đoạn làm nóng.
    warmups = []
    # Lưu một phần mẫu chi tiết để đưa vào Excel.
    raw_samples = []
    # Lưu lỗi hoặc nguyên nhân khiến bài thử không tiếp tục.
    diagnostics = []

    # Chỉ tạo đối tượng DB dành cho giám sát khi được bật.
    monitor_database = make_database(1, for_monitor=True) if config.monitor else None
    # Tạo bộ giám sát; kết nối riêng được mở trong mã Monitor.
    monitor = Monitor(monitor_database, config.monitor)

    def save_report():
        """Lưu trạng thái kết quả hiện tại."""
        # Lấy bản sao dữ liệu và lỗi giám sát hiện có.
        server_rows, monitor_errors = monitor.snapshot()

        # Mỗi khóa là tên một bảng dữ liệu trong báo cáo.
        tables = {
            "Summary": summaries,
            "Warmup": warmups,
            "RawSample": raw_samples,
            "ServerRequests": server_rows,
            "Diagnostics": diagnostics + monitor_errors,
            "Config": report_config,
            "ReadMe": [
                {"metric": key, "meaning": meaning}
                for key, meaning in METRICS
            ],
        }

        # Chuyển bảng dữ liệu thành chuỗi JSON dễ đọc.
        checkpoint_text = json.dumps(tables, default=str, ensure_ascii=False, indent=2)

        # Lưu JSON trước để vẫn có dữ liệu nếu Excel ghi thất bại.
        checkpoint_path = output_directory / "checkpoint.json"
        checkpoint_path.write_text(checkpoint_text, encoding="utf-8")

        try:
            # Xuất các bảng dữ liệu thành một tệp Excel.
            export_excel(output_directory / "report.xlsx", tables)

        except PermissionError:
            # Không khẳng định CSV đã có nếu chưa chạy giai đoạn đo.
            print("Không ghi được report.xlsx. Hãy đóng tệp Excel và kiểm tra quyền ghi. checkpoint.json đã được lưu.", flush=True)

    try:
        # Bắt đầu luồng giám sát nếu cấu hình cho phép.
        monitor.start()
        # Thử từng mức giới hạn đồng thời theo đúng thứ tự cấu hình.
        for capacity in capacities:
            # Tất cả luồng của mức này dùng chung đối tượng DB này.
            database = make_database(capacity)

            # Nếu không đặt số luồng riêng, dùng bằng capacity.
            workers = capacity if config.workers is None else config.workers

            # Có hàm chọn thao tác riêng thì bỏ phần tra cứu Users.
            if operation_factory is not None:

                # Tạo hàm thao tác dành cho đối tượng DB hiện tại.
                operation = operation_factory(database, config)

                # Phát hiện sớm trường hợp trả về sai kiểu dữ liệu.
                if not callable(operation):
                    raise TypeError("operation_factory phải trả về một hàm")

            else:
                # Danh sách ID phục vụ bài thử vừa xem danh sách, vừa xem chi tiết người dùng.
                user_ids = []

                # Nếu không chọn ping, cần kiểm tra dữ liệu trước khi tạo tải.
                if config.scenario != "ping":

                    # Kiểm tra từng trang trước khi tạo tải. Có thể thay hàm operation_factory để lấy danh sách người dùng từ bảng khác, nhưng bài thử này chỉ dùng bảng Users có sẵn.
                    for page in pages:
                        check = database.list_users_page( page, config.page_size)

                        # Yêu cầu trang có dữ liệu.
                        if (check.get("success") is not True or not check.get("users")):
                            diagnostics.append({
                                "component": "preflight",
                                "code": (
                                    check.get("code", "QUERY_FAILED")
                                    if check.get("success") is not True
                                    else "EMPTY_PAGE"
                                ),
                                "detail": f"Trang {page} lỗi hoặc rỗng; dừng bài thử danh sách người dùng.",
                            })
                            return

                        # Lấy ID để các luồng có thể chọn xem chi tiết.
                        user_ids.extend(user["UserId"] for user in check["users"])

                def operation(rng):
                    """
                    Thực hiện một thao tác người dùng có sẵn.
                    """

                    # Lựa chọn ping chỉ chạy một truy vấn rất nhỏ.
                    if config.scenario == "ping":
                        result = database._execute_query("SELECT 1 AS Ping",transactional=False,)

                        # Giữ cách đọc kết quả của lớp DB hiện tại.
                        return ("ping", result, len(result.get("data", [])))

                    # Khi chọn mixed, mỗi lượt có xác suất 50% thực hiện thao tác xem chi tiết.
                    if (config.scenario == "mixed" and rng.random() < 0.5):
                        # Bảo vệ trường hợp danh sách ID bị rỗng.
                        if not user_ids:
                            return ("get", {"success": False, "code": "NO_TEST_USER"}, 0)

                        # Chọn một ID trong dữ liệu đã kiểm tra.
                        user_id = rng.choice(user_ids)
                        # Thực hiện một lần xem chi tiết người dùng.
                        result = database.get_user(user_id=user_id)

                        # Có thể dữ liệu đã bị xóa sau bước kiểm tra.
                        if (result.get("success") and not result.get("user")):
                            result = dict(result, success=False, code="EXPECTED_USER_MISSING")

                        # Có người dùng thì tính một dòng; không có là 0.
                        return ("get", result, int(bool(result.get("user"))))

                    # Lựa chọn list, hoặc nửa còn lại của mixed, thực hiện lấy một trang người dùng.
                    page = rng.choice(pages)
                    result = database.list_users_page(page, config.page_size)

                    # Đánh dấu nếu trang kỳ vọng có dữ liệu lại rỗng.
                    if (result.get("success") and not result.get("users")):
                        result = dict(result, success=False, code="EXPECTED_PAGE_EMPTY")

                    # Một lần gọi lấy trang được tính một thao tác.
                    return ("list", result, len(result.get("users", [])))

            # Gọi thử đúng thao tác đã chọn trước khi chạy nhiều luồng.
            # Lượt kiểm tra này không tính vào kết quả đo chính.
            check_name, check_result, check_count = operation(random.Random(2026))

            # Bắt lỗi hợp đồng trả về của thao tác tự chọn.
            if not isinstance(check_name, str):
                raise TypeError("Tên thao tác phải là chuỗi")

            if not isinstance(check_result, dict):
                raise TypeError("Kết quả thao tác phải là dictionary")

            if type(check_count) is not int or check_count < 0:
                raise ValueError("Số dòng trả về phải là số nguyên không âm")

            # Không tạo tải nếu lần gọi kiểm tra đã thất bại.
            if check_result.get("success") is not True:
                diagnostics.append({
                    "component": "preflight",
                    "operation": check_name,
                    "code": str(check_result.get("code", "QUERY_FAILED")),
                })
                return

            # Ghi thao tác kiểm tra vào cấu hình để nhận diện bài thử.
            report_config.append({
                "setting": f"Kiểm_tra_trước_khi_chạy_capacity_{capacity}",
                "value": check_name,
            })

            # Cờ dùng để thoát các vòng lặp bên ngoài khi cần dừng.
            stop_levels = False

            # Lặp lại bài đo để so sánh độ ổn định giữa các lần.
            for repeat in range(1, config.repeats + 1):

                # Mỗi lần gồm làm nóng trước, đo chính sau.
                # Làm nóng giúp các kết nối được tạo sẵn, dữ liệu được cache và các luồng được khởi tạo trước khi đo chính. Khi đó kết quả đo chính sẽ phản ánh đúng hơn khả năng chịu tải của cơ sở dữ liệu.
                phases = [
                    ("warmup", config.warmup),
                    ("measure", config.seconds),
                ]

                # Thực hiện lần lượt hai giai đoạn.
                for phase, seconds in phases:

                    # Gắn nhãn cho các mẫu giám sát.
                    monitor.label = f"capacity={capacity};repeat={repeat};phase={phase}"
                    # Hiển thị tiến độ ngay trên terminal.
                    print(f"{phase}: capacity={capacity}, workers={workers}, repeat={repeat}", flush=True)

                    # Giao việc chạy nhiều luồng và đo thời gian cho hàm measure_phase đang có.
                    summary, samples = measure_phase(
                        db=database,
                        operation=operation,
                        capacity=capacity,
                        workers=workers,
                        seconds=seconds,
                        repeat=repeat,
                        phase=phase,
                        max_samples=config.max_samples,
                        think_ms=config.think_ms,
                        stop_ms=config.stop_ms,
                    )

                    # Chỉ đánh giá ngưỡng p95 ở giai đoạn đo chính.
                    if phase == "measure":
                        # Chỉ chấm tiếp nếu giai đoạn hoàn tất bình thường.
                        if summary["status"] == "COMPLETE":
                            # Quy tắc của bộ thử: cần ít nhất 100 mẫu.
                            if summary["successes"] < 100:
                                summary["status"] = ("INSUFFICIENT_SAMPLES")

                            # p95 là mốc thời gian mà khoảng 95%  thao tác thành công không vượt quá.
                            elif (summary["latency_p95_ms"] > config.p95_limit_ms):
                                summary["status"] = "P95_LIMIT"

                            # Đạt các điều kiện phía chương trình đo.
                            else:
                                summary["status"] = "PASS"

                        # Lưu tổng hợp của giai đoạn đo chính.
                        summaries.append(summary)
                    else:
                        # Lưu làm nóng riêng, không gộp vào đo chính.
                        warmups.append(summary)

                    # Tạo tên CSV riêng cho mức, lần lặp và giai đoạn.
                    csv_path = output_directory / (f"{capacity}_{repeat}_{phase}.csv")
                    # CSV giữ toàn bộ mẫu đã thu được của giai đoạn.
                    write_csv(csv_path, samples)

                    # Excel chỉ giữ một phần mẫu theo cấu hình.
                    raw_samples.extend(samples[:config.excel_samples])

                    # Cập nhật báo cáo sau mỗi giai đoạn.
                    save_report()

                    # In bảng tổng hợp để bạn theo dõi ngay.
                    print(json.dumps(summary, ensure_ascii=False), flush=True)

                    # Dừng nếu lỗi, chạm giới hạn mẫu hoặc không đạt ngưỡng.
                    if summary["status"] not in ("COMPLETE", "PASS"):
                        stop_levels = True
                        break

                # Thoát vòng lặp các lần đo.
                if stop_levels:
                    break

            # Thoát vòng các mức capacity và chỉ in thông báo một lần.
            if stop_levels:
                print("Dừng các lần đo tiếp theo. Xem trạng thái trong Summary hoặc Warmup, và thông tin trong Diagnostics.", flush=True)
                break

    except KeyboardInterrupt:
        # Ghi nhận khi người chạy chủ động yêu cầu ngắt.
        diagnostics.append({
            "component": "runner",
            "code": "INTERRUPTED",
        })

    except Exception as exc:
        # Chỉ ghi loại lỗi, tránh in nội dung có thể chứa thông tin đăng nhập.
        diagnostics.append({
            "component": "runner",
            "code": type(exc).__name__,
        })

        print("Bài kiểm thử gặp lỗi. Xem Diagnostics.", flush=True)

    finally:
        try:
            # Yêu cầu bộ giám sát dừng và hoàn tất việc dọn tài nguyên.
            monitor.close()
        finally:
            # Vẫn thử lưu báo cáo kể cả khi đóng giám sát có lỗi. Lỗi ghi tệp khác PermissionError vẫn có thể phát sinh.
            save_report()
            # In đường dẫn để mở thư mục kết quả.
            print("Kết quả:", output_directory.resolve(), flush=True)

def main():
    """Bấm Run sẽ chạy cấu hình ở đầu tệp."""
    run_benchmark(CONFIG)


if __name__ == '__main__':

    # Ví dụ muốn đổi câu truy vấn thử, hãy tạo hàm operation_factory riêng và truyền vào run_benchmark. Nếu không, sẽ dùng lựa chọn có sẵn.
    def create_product_list_test(database, config):
        """
        Ta cần hiểu rõ cách tạo hàm operation_factory. Nó phải nhận hai tham số: database và config, và trả về một hàm operation(rng).  
        Mỗi lần gọi operation(rng) sẽ thực hiện một thao tác thử nghiệm và trả về ba giá trị: tên thao tác, kết quả (dạng dict), và số dòng dữ liệu trả về.
        Hình dung:
        - create_operation() chuẩn bị bản hướng dẫn công việc.
        - operation() thực hiện một lượt công việc theo bản hướng dẫn đó.
        ```python
        def create_operation(database, config):
            # Chạy một lần khi chuẩn bị mỗi mức capacity.

            def operation(rng):
                # Chạy nhiều lần trong các luồng.
                ...
                return ten_thao_tac, ket_qua, so_dong

            return operation.
        ```
        """

        # Câu truy vấn cố định của bài thử.
        # ORDER BY giúp xác định rõ thứ tự lấy dữ liệu.
        query = """
            SELECT TOP (50)
                ProductId,
                ProductName,
                Quantity
            FROM dbo.Products
            ORDER BY ProductId;
        """

        def operation(rng):
            # Tạo một số ngẫu nhiên để sử dụng trong truy vấn.
            random_number = rng.randint(1, 100)
            # Hoặc có thể dùng random_number để thay đổi truy vấn, ví dụ: thêm điều kiện WHERE hoặc ORDER BY ngẫu nhiên.

            # Thực hiện một lần lấy danh sách hàng hóa.
            result = database._execute_query(query, transactional=False)

            # Lấy các dòng trả về theo hợp đồng của lớp cơ sở dữ liệu.
            rows = result.get("data") or []

            # Không coi trang rỗng là đại diện cho tải danh sách có dữ liệu.
            if result.get("success") is True and not rows:
                result = dict(
                    result,
                    success=False,
                    code="EXPECTED_PRODUCTS_MISSING",
                )

            # Trả đúng ba thành phần mà measure_phase yêu cầu.
            return "danh_sach_hang_hoa", result, len(rows)

        return operation
    # Sau khi tạo hàm operation_factory, hãy truyền nó vào run_benchmark. Nếu không, sẽ dùng lựa chọn có sẵn.
    # run_benchmark(CONFIG, operation_factory=create_stock_report_test)
    main()
