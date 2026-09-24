



# Config
Giả sử:  
```bash
workers = 5
capacity = 2
```
Đặt tên 5 luồng là A, B, C, D, E cho dễ hình dung.  
Một diễn biến có thể xảy ra như sau:  

| Thời điểm    | Đang sử dụng cơ sở dữ liệu |      Đang chờ lượt            |
| ------------ | -------------------------: | ----------------------------: |
| Bắt đầu      |           A, B             |  C, D, E                      |
| A hoàn thành |           B, C             |  D, E và A nếu A gửi lượt mới |
| B hoàn thành |           C, D             |  E và các luồng muốn làm tiếp |
| C hoàn thành |           D, E             |  Các luồng khác               

Thứ tự trên chỉ minh họa. Bộ cấp lượt không bảo đảm các luồng luôn được phục vụ theo đúng thứ tự A, B, C, D, E.  
Mỗi luồng làm liên tục: `Nhận một lượt công việc → thực hiện → ghi kết quả → làm lượt tiếp theo.`  
## Hàm sử dụng câu truy vấn danh sách user
Một thao tac có nghĩa là:  
```python
name, result, count = operation(rng)
```
Tức là 1 lần gọi hàm `operation`, sau đó ghi nhận kết quả thành một mẫu.  
Ví dụ với thao tác lấy danh sách người dùng, sử dụng phân trang `db.list_users_page(page, page_size)`:  
| Công việc                                        | Số thao tác |            Số dòng trả về |
| ------------------------------------------------ | ----------: | ------------------------: |
| Lấy trang 1 một lần, nhận 3 người dùng           |           1 |                         3 |
| Lấy trang 1 mười lần, mỗi lần nhận 3 người dùng  |          10 |                        30 |
| Lấy một trang chứa 50 người dùng                 |           1 |                        50 |
| Gọi lấy danh sách nhưng gặp lỗi và được ghi nhận |           1 | Theo mẫu lỗi, thường là 0 |

Hoặc gọi 1 procedure, trong procedure ấy gọi 3 lệnh truy vấn thì vẫn chỉ tính là 1 thao tác. Không phụ thuộc hàm đó làm gì, chỉ tính alf 1 thao tác khi gọi hàm `operation` 1 lần và nhận về kết quả  
Ví dụ:  
```bash
attempts = 50.000
rows_total = 150.000
```
Thì bài đo đã ghi nhận 50.000 lần lấy danh sách. Tổng số dòng người dùng nhận được qua các lần lấy là 150.000, trung bình 3 dòng mỗi lần.  

# Cấp quyền monitor  
Để có thể quán sát hệ thống SQL Server, ta cần làm như sau:  
## 1. Tạo tên ứng dụng
Tên ứng dụng giúp ta dễ nhận diện và lọc kết nối tốt hơn.  
Ta khai báo tên ứng dụng tại chuỗi kết nối của database bằng từ khóa `APP=DucQuanApp.Benchmark;`. mỗi chương trình ta thay đổi `DucQuanApp.Benchmark` để có thể nhận biết tốt hơn.  
```python
# Tạo chuỗi kết nối ODBC cho SQL Server
self._connection_string = (
    f'DRIVER={_odbc_value(driver)};'
    f'SERVER={_odbc_value(server_name)};'
    f'DATABASE={_odbc_value(database_name)};'
    f'{auth}Encrypt=yes;'
    f'APP=DucQuanApp.Benchmark;' # Tên ứng dụng để SQL Server log trace hoặc khi benchmark, có thể dùng 'APP=DucQuanApp.Benchmark;'
    f'TrustServerCertificate={"yes" if trust_server_certificate else "no"};'
)
```
Ta thêm tên ứng dụng cho chuỗi kết nối ở tệp `database_service.py`  
Để xem ứng dụng nào đang gọi tới truy vấn ta có thể chạy lệnh sau:  
```SQL
SELECT
    session_id,
    login_name,
    host_name,
    host_process_id,
    program_name,
    status
FROM sys.dm_exec_sessions
WHERE is_user_process = 1
ORDER BY program_name, session_id;
```
Nó sẽ trả về danh sách kết nối, và tên ứng dụng hiển thị ở program_name  

|session_id	| login_nam     |host_name	|host_process_id	|program_name	    |status     |
| --------- | ------------: | --------: |-----------------: |-----------------: |--------:  |
|65	        | DucQuan	    |DUCQUAN	|15436	            |Microsoft SQL ...  |sleeping   |
|66	        | DucQuan	    |DUCQUAN	|15436	            |Microsoft SQL ...  |running    |
|89	        | DucQuan	    |DUCQUAN	|15436	            |Microsoft SQL ...	|sleeping   |
|51	        | NT SERVICE... |DUCQUAN	|22764	            |SQLServerCEIP	    |sleeping   |

## 2. Tài khoản có quyền xem hệ thống
Ta cần kiểm tra xem tài khoản đang đăng nhập có quyền truy cập hệ thống hay không bằng cách đăng nhập tài khoản quản trị viên và chạy lệnh bên dưới:  
```SQL
USE master;
GO

-- Kiểm tra đang thao tác trên máy chủ nào và phiên bản nào.
SELECT
    SERVERPROPERTY('ServerName') AS ServerName,
    SERVERPROPERTY('InstanceName') AS InstanceName,
    SERVERPROPERTY('ProductVersion') AS ProductVersion,
    ORIGINAL_LOGIN() AS LoginDangSuDung;
GO

-- Xác nhận SQL login của ứng dụng tồn tại trên máy chủ này.
SELECT
    name,
    type_desc,
    is_disabled
FROM sys.server_principals
WHERE name = N'ducquan_user';
GO
```
Nếu kết quả trả về:  

|name	        |type_desc	|is_disabled  |
| ---------     | --------: | ----------: |
|ducquan_user	|SQL_LOGIN	|0            |

Ta thấy trạng thái `is_disables = 0` có nghĩa là tài khoản `ducquan_user` không có quyền truy cập hệ thống.  
Ta có thể sử dụng tài khoản có quyền truy cập hệ thống để test bằng cách cung cấp tài khoản vào hai trường `monitor_user_name` và `monitor_password` trong `config`. Hoặc ta có thể cấp quyền cho tài khoản `ducquan_user` bằng cách chạy lệnh sau:  
```SQL
USE master;
GO
IF CONVERT(INT, SERVERPROPERTY('ProductMajorVersion')) >= 16
BEGIN
    -- SQL Server 2022 trở lên.
    EXEC(N'
        GRANT VIEW SERVER PERFORMANCE STATE
        TO [ducquan_user];
    ');
END
ELSE
BEGIN
    -- SQL Server 2019 và các phiên bản trước đó.
    EXEC(N'
        GRANT VIEW SERVER STATE
        TO [ducquan_user];
    ');
END;
GO
```
Sau đó đăng nhập lại tài khoản `ducquan_user` và chạy lệnh kiểm tra người dùng:  
```SQL
-- Kiểm tra danh tính của kết nối hiện tại.
SELECT
    SERVERPROPERTY('ServerName') AS ServerName,
    ORIGINAL_LOGIN() AS OriginalLogin,
    SUSER_SNAME() AS CurrentLogin,
    DB_NAME() AS CurrentDatabase;
GO

-- Xác định tên quyền cần có.
DECLARE @RequiredPermission SYSNAME;

SET @RequiredPermission =
    CASE
        WHEN CONVERT(
            INT,
            SERVERPROPERTY('ProductMajorVersion')
        ) >= 16
        THEN N'VIEW SERVER PERFORMANCE STATE'
        ELSE N'VIEW SERVER STATE'
    END;

-- Kiểm tra quyền thực tế của chính tài khoản đang đăng nhập.
SELECT
    @RequiredPermission AS RequiredPermission,
    HAS_PERMS_BY_NAME(
        NULL,
        NULL,
        @RequiredPermission
    ) AS HasPermission;
GO
```
Và kết quả sẽ như sau là thành công  
|RequiredPermission	            |HasPermission	|
| ----------------------------- | ------------: |
|VIEW SERVER PERFORMANCE STATE	|1	            |
# Cách đọc kết quả
Với kết quả:  
capacity	workers	repeat	phase	started_utc	elapsed_s	attempts	successes	errors	error_rate	success_ops_s	status	rows_total	latency_p50_ms	latency_p95_ms	latency_p99_ms	latency_max_ms	wait_p95_ms	connect_p95_ms	work_p95_ms	lease_p95_ms
4	4	1	measure	2026-09-24T09:49:56.823+00:00	30.00	79029	79029	0	0.00%	2,634.11	PASS	237087	1.34	2.68	4.83	15.05	0.00	0.19	2.25	2.62
4	4	2	measure	2026-09-24T09:50:35.278+00:00	30.00	68751	68751	0	0.00%	2,291.56	PASS	206253	1.67	2.51	2.95	27.45	0.00	0.24	2.10	2.45
4	4	3	measure	2026-09-24T09:51:14.836+00:00	30.00	73564	73564	0	0.00%	2,452.01	PASS	220692	1.56	2.30	2.70	40.82	0.00	0.23	1.91	2.24
6	6	1	measure	2026-09-24T09:51:56.085+00:00	30.00	51817	51817	0	0.00%	1,727.10	PASS	155451	3.35	5.60	6.77	16.62	0.00	0.31	5.12	5.54
6	6	2	measure	2026-09-24T09:52:38.494+00:00	30.00	40689	40689	0	0.00%	1,356.12	PASS	122067	4.48	5.89	6.58	34.49	0.00	0.36	5.37	5.83
6	6	3	measure	2026-09-24T09:53:22.068+00:00	30.00	40721	40721	0	0.00%	1,357.26	PASS	122163	4.47	5.89	6.67	14.53	0.00	0.36	5.38	5.83
8	8	1	measure	2026-09-24T09:54:07.426+00:00	30.03	36226	36226	0	0.00%	1,206.40	PASS	108678	6.61	9.04	10.27	124.01	0.00	0.44	8.42	8.98
8	8	2	measure	2026-09-24T09:54:54.035+00:00	30.01	35092	35092	0	0.00%	1,169.52	PASS	105276	6.88	9.16	10.42	121.27	0.00	0.45	8.52	9.09
8	8	3	measure	2026-09-24T09:55:42.301+00:00	30.00	34874	34874	0	0.00%	1,162.32	PASS	104622	6.95	9.15	10.29	21.66	0.00	0.46	8.52	9.09

Ta có bảng kết luận như sau:  

| Tiêu chí                              |                   Mức 4 |               Mức 6 |                 Mức 8 |
| ------------------------------------- | ----------------------: | ------------------: | --------------------: |
| Số luồng                              |                       4 |                   6 |                     8 |
| Thao tác thành công/giây trung bình   |            **2.459,23** |            1.480,16 |              1.179,41 |
| Thay đổi so với mức 4                 |                       — |      **Giảm 39,8%** |        **Giảm 52,0%** |
| Khoảng thời gian ở mốc 95% qua ba lần | **2,30–2,68 mili giây** | 5,60–5,89 mili giây |   9,04–9,16 mili giây |
| Khoảng thời gian ở mốc 99% qua ba lần | **2,70–4,83 mili giây** | 6,58–6,77 mili giây | 10,27–10,42 mili giây |
| Thao tác chậm nhất đã quan sát        |         40,82 mili giây |     34,49 mili giây |      124,01 mili giây |
| Lỗi thao tác                          |                       0 |                   0 |                     0 |

Ta có thể hiểu  

> Với công việc đang thử, cho 4 luồng làm cùng lúc đạt khoảng 2.459 lượt mỗi giây. Tăng lên 8 luồng thì mỗi lượt chậm hơn đáng kể, khiến cả nhóm chỉ hoàn thành khoảng 1.179 lượt mỗi giây.  

Để đọc chi tiết ta đi từng cột:  
```bash
capacity = 4
workers = 4
repeat = 1
phase = measure
```
Nghĩa là: 
- Đối tượng cơ sở dữ liệu được cấu hình tối đa 4 lượt sử dụng đồng thời.
- Có 4 luồng liên tục gửi công việc.
- Đây là lần lặp thứ nhất.
- Số liệu thuộc giai đoạn đo chính, không phải làm nóng.

Thời gian bắt đầu `(started_utc = 2026-09-24T09:49:56.823+00:00)` tương ứng với `16 giờ 49 phút 56,823 giây ngày 24/09/2026` tại `Việt Nam`, vì giờ UTC nên phải cộng thêm 7 tiếng.  
Tổng thời gian đo cho 1 lượt `elapsed_s = 30.00` là `30s`.  

kết quả thu được cho giai đoạn này như sau:  
```bash
attempts = 79029
successes = 79029
errors = 0
```
Chương trình ghi nhận` 79.029` lần gọi thao tác, tất cả thành công theo tiêu chí của bộ đo. Và `success_ops_s = 2634.11` là trung bình `2634 thao tác / giây`.  
Với `rows_total = 237087` thì có nghĩa là `237.087 / 79.029 = 3 dòng/thao tác.` Dữ liệu truy vấn được chỉ có 3 dòng.  
Về thời gian phản hồi ta có:  
```bash
latency_p50_ms = 1.34
latency_p95_ms = 2.68
latency_p99_ms = 4.83
latency_max_ms = 15.05
```
| Chỉ số   | Ý nghĩa                                                      |
| -------- | ------------------------------------------------------------ |
| Mốc 50%  | Khoảng một nửa thao tác thành công không vượt 1,34 mili giây |
| Mốc 95%  | Khoảng 95% thao tác thành công không vượt 2,68 mili giây     |
| Mốc 99%  | Khoảng 99% thao tác thành công không vượt 4,83 mili giây     |
| Lớn nhất | Thao tác chậm nhất mất 15,05 mili giây                       |

Và thời gian kết nối như sau:  
| Thành phần                           |         Mức 4 |         Mức 6 |         Mức 8 |
| ------------------------------------ | ------------: | ------------: | ------------: |
| Chờ semaphore ở mốc 95%              | Hiển thị 0,00 | Hiển thị 0,00 | Hiển thị 0,00 |
| Lấy/thiết lập kết nối ở mốc 95%      |     0,19–0,24 |     0,31–0,36 |     0,44–0,46 |
| Làm việc với cơ sở dữ liệu ở mốc 95% | **1,91–2,25** | **5,12–5,38** | **8,42–8,52** |

Vì `capacity = worker` hay `Số luồng = số lượt truy cập cho phép` nên thời gian chờ `semaphore` như vậy là hợp lý. Thành phần tăng rõ nhất khi chuyển từ 4 lên 6 và 8 là `work_p95_ms`.  
Tuy nhiên, trong lớp đo, thời gian này bao gồm phần làm việc phía Python, trình kết nối, chờ SQL Server, thực thi và nhận dữ liệu theo phạm vi đã đo. Nó không phải thời gian bộ xử lý của SQL Server thuần túy.  

Một số nguyên nhân khi tăng số luồng lên thì lại chậm hơn như sau:  
| Khả năng                                                               | Dữ liệu cần xem thêm                               |
| ---------------------------------------------------------------------- | -------------------------------------------------- |
| Máy chạy Python tốn nhiều tài nguyên khi quản lý thêm luồng và ghi mẫu | Mức sử dụng bộ xử lý, bộ nhớ của tiến trình Python |
| SQL Server phải chia sẻ tài nguyên giữa nhiều yêu cầu                  | Bộ xử lý, trạng thái chờ và yêu cầu đang chạy      |
| Python và SQL Server cùng chạy trên một máy                            | Mức sử dụng tài nguyên của cả hai tiến trình       |
| Có chương trình khác tạo tải trong lúc đo                              | Tài nguyên máy và hoạt động SQL cùng thời điểm     |
| Hiệu năng thay đổi theo thời gian chạy                                 | Chạy lại với thứ tự các mức khác nhau              |
| Truy vấn rất nhỏ khiến chi phí phía chương trình trở nên đáng kể       | So sánh với workload lớn hơn, gần dữ liệu thực tế  |

## 1. Thay đổi số luồng kết nối
Đối với kết quả trên, ta chưa thấy lợi ích nào nên tăng số luồng lên 6 hay 8. Ta có thể thử lại với `"capacities": [1, 2, 3, 4, 6, 8]` và sau đó `"capacities": [8, 6, 4, 3, 2, 1],` để xem mức 4 có tốt hơn khi không còn được chạy trước hay không.  

## 2. giữ nguyên số luồng kết nối, giới hạn truy cập
```bash
"capacities": [2, 4, 6, 8],
"workers": 8,
```
Với cách này ta có thể biết được:  

> Với cùng 8 luồng muốn làm việc, cho phép bao nhiêu lượt truy cập đồng thời thì đạt hiệu quả tốt hơn?  

Theo dõi cả thời gian chờ semaphore. Giới hạn thấp có thể làm thời gian chờ tăng nhưng vẫn giúp tổng số công việc hoàn thành cao hơn.