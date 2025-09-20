# -*- coding: utf-8 -*-
"""
Tiện ích đọc/ghi JSON cấu hình dùng chung cho GUI
- Lưu trữ các thông số: server, driver, auth_mode, username (không lưu password rõ nếu không cần),
  danh sách DB được chọn, thư mục backup, lịch backup (FULL/DIFF/LOG) v.v.
- Thiết kế "an toàn": nếu file chưa tồn tại -> trả về mặc định; nếu lỗi -> ghi log và trả mặc định.
"""
import json
import os
from typing import Any, Dict

DEFAULT_CONFIG: Dict[str, Any] = {
    "connection": {
        "driver": None,
        "server": None,
        "auth_mode": "sql",   # hoặc "windows"
        "username": None,
        # password KHÔNG nên lưu rõ; tuỳ bạn lưu tạm session hoặc vault
    },
    "storage": {
        "backup_dir": None,    # thư mục lưu trên máy SQL Server (ổ cục bộ/UNC)
    },
    "databases": [],            # danh sách DB được chọn backup
    "schedule": {
        # Ví dụ lịch (bạn thay theo chuẩn của bạn)
        "full": "0 0 * * 0",     # Chủ nhật 00:00 (CRON)
        "diff": "30 0 * * 1-6",   # T2-T7 00:30
        "log":  "*/15 * * * *",   # mỗi 15 phút
    }
}


def ensure_parent(path: str) -> None:
    """Đảm bảo thư mục cha tồn tại trước khi ghi file."""
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)


def load_config(path: str) -> Dict[str, Any]:
    """Đọc JSON config nếu có; nếu không có/ lỗi -> trả về DEFAULT_CONFIG (deep copy)."""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            # Hợp nhất thiếu key với mặc định (đảm bảo không lỗi key)
            cfg = DEFAULT_CONFIG.copy()
            for k, v in data.items():
                cfg[k] = v
            # Deep merge cho nhánh con đơn giản (connection/storage/schedule)
            for sub in ("connection", "storage", "schedule"):
                if sub in DEFAULT_CONFIG and sub in cfg and isinstance(DEFAULT_CONFIG[sub], dict) and isinstance(cfg[sub], dict):
                    merged = DEFAULT_CONFIG[sub].copy()
                    merged.update(cfg[sub])
                    cfg[sub] = merged
            if "databases" not in cfg or not isinstance(cfg["databases"], list):
                cfg["databases"] = []
            return cfg
    except Exception:
        pass
    # Trả về copy để tránh đụng DEFAULT_CONFIG gốc
    import copy
    return copy.deepcopy(DEFAULT_CONFIG)


def save_config(path: str, data: Dict[str, Any]) -> None:
    """Ghi JSON config ra đĩa (tạo thư mục nếu cần)."""
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)