# -*- coding: utf-8 -*-
"""
DashboardFrame (tooltip ổn định + pie tooltip + sửa màu + trục & nhãn)
- KPI cards
- Biểu đồ cột + đường có trục X/Y, tick, nhãn, giá trị
- Biểu đồ tròn (pie chart) + legend + nhãn %
- Tooltip khi hover trên cột, điểm đường, và lát pie
- Khắc phục việc tooltip bị nhân bản / không biến mất
"""

import os
import math
import json
import random
import datetime as dt
import customtkinter as ctk
from tkinter import ttk
from typing import Dict, Any, List, Tuple, Optional


_SAMPLE_FILE = "dashboard_sample.json"  # nếu tồn tại sẽ đọc; nếu không sẽ sinh dữ liệu mẫu


class DashboardFrame(ctk.CTkFrame):
    def __init__(self, parent, owner_page):
        super().__init__(parent)
        self.owner = owner_page

        # Vùng hit-test để tooltip (combo chart)
        self._bar_regions: List[dict] = []     # {x0,y0,x1,y1,label,value}
        self._line_points: List[dict] = []     # {cx,cy,label,value}

        # Trạng thái pie để hit-test tooltip
        self._pie_state: Dict[str, Any] = {
            "cx": 0, "cy": 0, "r": 0,
            "slices": [],   # list of {label, value, start, extent}
            "total": 1
        }

        # Debounce ẩn tooltip
        self._hide_after_id: Optional[str] = None

        # Bố cục:
        self.grid_rowconfigure(2, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        # --- Tiêu đề ---
        ctk.CTkLabel(self, text="Dashboard", font=ctk.CTkFont(size=18, weight="bold")).grid(
            row=0, column=0, padx=16, pady=(16, 8), sticky="w"
        )

        # --- Dữ liệu ---
        self.data = self._load_or_build()
        cards = self.data["cards"]

        # --- KPI Cards ---
        cards_row = ctk.CTkFrame(self)
        cards_row.grid(row=1, column=0, padx=16, pady=8, sticky="ew")
        cards_row.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self._kpi_card(cards_row, 0, "Databases", str(cards["databases"]))
        self._kpi_card(cards_row, 1, "Backups (24h)", str(cards["backups_24h"]))
        self._kpi_card(cards_row, 2, "Failures (7d)", str(cards["failures_7d"]))
        self._kpi_card(cards_row, 3, "Storage Used", cards["storage_used"])

        # --- Khu chart: cột+đường & pie ---
        charts_wrap = ctk.CTkFrame(self)
        charts_wrap.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="nsew")
        charts_wrap.grid_columnconfigure(0, weight=2)
        charts_wrap.grid_columnconfigure(1, weight=1)
        charts_wrap.grid_rowconfigure(0, weight=1)

        bg_color = self._resolve_color(self.cget("fg_color"))

        self.combo_canvas = ctk.CTkCanvas(charts_wrap, highlightthickness=0, bg=bg_color)
        self.combo_canvas.grid(row=0, column=0, sticky="nsew", padx=(8, 8), pady=8)

        self.pie_canvas = ctk.CTkCanvas(charts_wrap, highlightthickness=0, bg=bg_color)
        self.pie_canvas.grid(row=0, column=1, sticky="nsew", padx=(8, 8), pady=8)

        # Tooltip: tạo đúng 1 toplevel, ẩn sẵn
        self._tip_win = ctk.CTkToplevel(self)
        self._tip_win.overrideredirect(True)
        self._tip_win.withdraw()
        self._tip_win.attributes("-topmost", True)
        self._tip_lbl = ctk.CTkLabel(
            self._tip_win, text="", fg_color="#111827", text_color="#e5e7eb",
            corner_radius=6, padx=8, pady=6, font=ctk.CTkFont(size=11)
        )
        self._tip_lbl.pack()

        # Vẽ lần đầu
        self._redraw_charts()

        # Redraw & ẩn tooltip khi thay đổi kích thước
        self.combo_canvas.bind("<Configure>", lambda e: (self._hide_tooltip(force=True), self._redraw_charts()))
        self.pie_canvas.bind("<Configure>", lambda e: (self._hide_tooltip(force=True), self._redraw_charts()))

        # Hover events (combo & pie)
        self.combo_canvas.bind("<Motion>", self._on_combo_motion)
        self.combo_canvas.bind("<Leave>", self._on_canvas_leave)

        self.pie_canvas.bind("<Motion>", self._on_pie_motion)
        self.pie_canvas.bind("<Leave>", self._on_canvas_leave)

        # --- Bảng Recent Jobs ---
        tbl = ctk.CTkFrame(self)
        tbl.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="nsew")
        tbl.grid_rowconfigure(0, weight=1)
        tbl.grid_columnconfigure(0, weight=1)

        self.tv = ttk.Treeview(
            tbl, columns=("when", "db", "type", "status", "size"), show="headings"
        )
        for col, w in ("when", 160), ("db", 180), ("type", 90), ("status", 90), ("size", 90):
            self.tv.heading(col, text=col.title())
            self.tv.column(col, width=w, anchor="w")
        self.tv.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(tbl, orient="vertical", command=self.tv.yview)
        self.tv.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns")

        for j in self.data["recent_jobs"]:
            self.tv.insert("", "end", values=(j["when"], j["db"], j["type"], j["status"], j["size"]))

    # ---------------------------------------------------------------------
    # VẼ BIỂU ĐỒ
    # ---------------------------------------------------------------------

    def _redraw_charts(self):
        """Vẽ lại cả 2 canvas; luôn ẩn tooltip để tránh “kẹt” tooltip cũ."""
        self._hide_tooltip(force=True)

        bars = self.data["bar_series"]
        line = self.data["line_series"]

        # Combo chart
        self._draw_combo_chart(self.combo_canvas, bars, line, x_labels=[f"M{i+1}" for i in range(len(bars))])

        # Pie chart
        pie_data = [
            ("FULL", max(1, sum(bars[:4]) // 4 if bars else 5)),
            ("DIFF", max(1, sum(bars[4:8]) // 4 if bars else 4)),
            ("LOG",  max(1, sum(bars[8:]) // 4 if bars else 7)),
        ]
        self._draw_pie_chart(self.pie_canvas, pie_data, title="Tỷ lệ backup 24h")

    # ------------------ COMBO CHART (CỘT + ĐƯỜNG) ------------------

    def _draw_combo_chart(self, canvas: ctk.CTkCanvas, bars: List[int], line: List[int], x_labels: List[str]):
        canvas.delete("all")
        self._bar_regions.clear()
        self._line_points.clear()

        w = max(480, canvas.winfo_width() or 800)
        h = max(280, canvas.winfo_height() or 280)

        left, right, top, bottom = 56, 24, 20, 48
        inner_w = w - left - right
        inner_h = h - top - bottom
        if inner_w <= 0 or inner_h <= 0:
            return

        baseline_y = h - bottom
        axis_color = "#94a3b8"
        tick_text = "#9ca3af"
        canvas.create_line(left, baseline_y, left, top, fill=axis_color)
        canvas.create_line(left, baseline_y, w - right, baseline_y, fill=axis_color)

        n = max(len(bars), len(line))
        if n == 0:
            return
        max_v = max(bars + line) if (bars or line) else 1
        max_v = max(1, max_v)

        ticks = 5
        step_v = (max_v + (ticks - 1)) // ticks
        if step_v == 0:
            step_v = 1
        y_values = [i * step_v for i in range(0, ticks + 1)]
        for v in y_values:
            y = baseline_y - int(inner_h * (v / (step_v * ticks)))
            canvas.create_line(left - 4, y, left, y, fill=axis_color)
            canvas.create_text(left - 8, y, text=str(v), anchor="e", fill=tick_text, font=("Arial", 9))

        canvas.create_text(left, h - 8, text="Trục X", anchor="w", fill=tick_text, font=("Arial", 10, "italic"))
        canvas.create_text(8, top, text="Trục Y", anchor="w", fill=tick_text, font=("Arial", 10, "italic"))

        gap = max(6, inner_w // (n * 6))
        bar_w = max(10, (inner_w - gap * (n + 1)) // n)
        x = left + gap

        bar_color = "#60a5fa"
        value_on_bar = "#e5e7eb"
        x_centers: List[int] = []

        for i in range(n):
            v = bars[i] if i < len(bars) else 0
            bh = int(inner_h * (v / (step_v * ticks)))
            x0, y0 = x, baseline_y - bh
            x1, y1 = x + bar_w, baseline_y
            canvas.create_rectangle(x0, y0, x1, y1, fill=bar_color, width=0)
            canvas.create_text((x0 + x1) // 2, y0 - 10, text=str(v), fill=value_on_bar, font=("Arial", 9, "bold"))
            lbl = x_labels[i] if i < len(x_labels) else f"{i+1}"
            canvas.create_text((x0 + x1) // 2, baseline_y + 14, text=lbl, fill="#cbd5e1", font=("Arial", 9))
            self._bar_regions.append({"x0": x0, "y0": y0, "x1": x1, "y1": y1, "label": lbl, "value": v})
            x_centers.append((x0 + x1) // 2)
            x += bar_w + gap

        line_color = "#34d399"
        marker_r = 3
        pts: List[Tuple[int, int]] = []

        for i in range(n):
            v = line[i] if i < len(line) else 0
            lh = int(inner_h * (v / (step_v * ticks)))
            cx = x_centers[i] if i < len(x_centers) else (left + gap + bar_w // 2 + i * (bar_w + gap))
            cy = baseline_y - lh
            pts.append((cx, cy))

        for i in range(1, len(pts)):
            canvas.create_line(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1], fill=line_color, width=2)

        for i, (cx, cy) in enumerate(pts):
            canvas.create_oval(cx - marker_r, cy - marker_r, cx + marker_r, cy + marker_r, fill=line_color, width=0)
            v = line[i] if i < len(line) else 0
            canvas.create_text(cx + 12, cy - 10, text=str(v), fill="#86efac", font=("Arial", 9, "bold"), anchor="w")
            lbl = x_labels[i] if i < len(x_labels) else f"{i+1}"
            self._line_points.append({"cx": cx, "cy": cy, "label": lbl, "value": v})

        canvas.create_rectangle(w - right - 150, top + 6, w - right - 10, top + 40, outline="#475569")
        canvas.create_rectangle(w - right - 140, top + 12, w - right - 120, top + 26, fill=bar_color, width=0)
        canvas.create_text(w - right - 115, top + 19, text="Cột (bar_series)", anchor="w", fill="#cbd5e1", font=("Arial", 9))
        canvas.create_line(w - right - 140, top + 32, w - right - 120, top + 32, fill=line_color, width=2)
        canvas.create_text(w - right - 115, top + 32, text="Đường (line_series)", anchor="w", fill="#cbd5e1", font=("Arial", 9))

    # --------------------------- PIE CHART ---------------------------

    def _draw_pie_chart(self, canvas: ctk.CTkCanvas, items: List[Tuple[str, int]], title: str = ""):
        canvas.delete("all")
        self._pie_state.update({"slices": [], "total": 1})

        w = max(260, canvas.winfo_width() or 320)
        h = max(260, canvas.winfo_height() or 260)

        cx, cy = w // 2 - 20, h // 2
        r = min(w, h) // 3

        total = sum(max(0, v) for _, v in items) or 1
        palette = ["#60a5fa", "#34d399", "#fbbf24", "#f87171", "#a78bfa", "#fb7185", "#4ade80"]

        if title:
            canvas.create_text(12, 10, text=title, fill="#e5e7eb", anchor="w", font=("Arial", 11, "bold"))

        bg_color = self._resolve_color(self.cget("fg_color"))

        start = 0.0
        for idx, (label, value) in enumerate(items):
            extent = (value / total) * 360.0
            color = palette[idx % len(palette)]
            canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start, extent=extent,
                fill=color, outline=bg_color, width=1, style="pieslice"
            )
            # Nhãn %
            mid_angle = (start + start + extent) / 2.0
            rad = math.radians(mid_angle)
            tx = cx + int(r * 0.6 * math.cos(rad))
            ty = cy - int(r * 0.6 * math.sin(rad))
            pct = f"{(value / total) * 100:.0f}%"
            canvas.create_text(tx, ty, text=pct, fill="#0f172a", font=("Arial", 9, "bold"))

            # Lưu lát để hit-test
            self._pie_state["slices"].append({
                "label": label, "value": value, "start": start, "extent": extent, "color": color
            })
            start += extent

        # Legend
        legend_x = cx + r + 16
        if legend_x + 130 > w:
            legend_x = w - 130
        y = 36
        for s in self._pie_state["slices"]:
            pct = (s["value"] / total) * 100.0
            canvas.create_rectangle(legend_x, y, legend_x + 14, y + 14, fill=s["color"], width=0)
            canvas.create_text(
                legend_x + 18, y + 7,
                text=f"{s['label']}: {s['value']} ({pct:.0f}%)",
                anchor="w", fill="#cbd5e1", font=("Arial", 9)
            )
            y += 20

        # Cập nhật tâm, bán kính & total cho hit-test tooltip
        self._pie_state.update({"cx": cx, "cy": cy, "r": r, "total": total})

    # ---------------------------------------------------------------------
    # Tooltip & Hit-test
    # ---------------------------------------------------------------------

    def _on_canvas_leave(self, _event=None):
        """Khi rời khỏi bất kỳ canvas nào -> ẩn tooltip."""
        self._hide_tooltip()

    def _on_combo_motion(self, event):
        """Hover trên combo chart: ưu tiên điểm line, sau đó tới cột."""
        x, y = event.x, event.y

        pt = self._hit_line_point(x, y, radius=6)
        if pt:
            self._show_tooltip_at(event.widget, x, y, f"{pt['label']}\nLine: {pt['value']}")
            return

        bar = self._hit_bar(x, y)
        if bar:
            self._show_tooltip_at(event.widget, x, y, f"{bar['label']}\nBar: {bar['value']}")
        else:
            self._hide_tooltip()

    def _on_pie_motion(self, event):
        """Hover trên pie chart: xác định lát đang trỏ và hiển thị tooltip."""
        info = self._hit_pie(event.x, event.y)
        if info:
            label, value, pct = info
            self._show_tooltip_at(event.widget, event.x, event.y, f"{label}\n{value} ({pct:.0f}%)")
        else:
            self._hide_tooltip()

    # --- hit-test helpers ---
    def _hit_bar(self, x: int, y: int):
        for reg in self._bar_regions:
            if reg["x0"] <= x <= reg["x1"] and reg["y0"] <= y <= reg["y1"]:
                return reg
        return None

    def _hit_line_point(self, x: int, y: int, radius: int = 6):
        rsq = radius * radius
        for pt in self._line_points:
            dx = x - pt["cx"]
            dy = y - pt["cy"]
            if dx * dx + dy * dy <= rsq:
                return pt
        return None

    def _hit_pie(self, x: int, y: int):
        """Trả về (label, value, pct) nếu (x,y) nằm trong lát pie; ngược lại None."""
        cx, cy, r = self._pie_state["cx"], self._pie_state["cy"], self._pie_state["r"]
        if r <= 0:
            return None
        dx, dy = x - cx, cy - y  # chú ý trục y ngược
        dist2 = dx * dx + dy * dy
        if dist2 > r * r:
            return None

        ang = math.degrees(math.atan2(dy, dx))
        if ang < 0:
            ang += 360.0

        total = self._pie_state.get("total", 1) or 1
        for s in self._pie_state["slices"]:
            start, extent = s["start"], s["extent"]
            end = start + extent
            # Vì Tkinter đo từ 0 theo chiều ngược kim đồng hồ, logic sau phù hợp
            if start <= ang <= end:
                return s["label"], s["value"], (s["value"] / total) * 100.0
        return None

    # --- tooltip core ---
    def _show_tooltip_at(self, widget, x: int, y: int, text: str):
        """Hiển thị tooltip tại toạ độ (x,y) tương đối của `widget`."""
        # Hủy lịch ẩn nếu đang chờ
        if self._hide_after_id:
            try:
                self.after_cancel(self._hide_after_id)
            except Exception:
                pass
            self._hide_after_id = None

        # Cập nhật nội dung
        self._tip_lbl.configure(text=text)

        # Vị trí tuyệt đối theo màn hình
        x_root = widget.winfo_rootx() + x + 16
        y_root = widget.winfo_rooty() + y + 16

        # Đặt vị trí và hiện lên (không tạo mới)
        self._tip_win.geometry(f"+{x_root}+{y_root}")
        self._tip_win.deiconify()

    def _hide_tooltip(self, force: bool = False):
        """Ẩn tooltip ngay (force=True) hoặc sau một khoảng ngắn (debounce)."""
        if force:
            if self._hide_after_id:
                try:
                    self.after_cancel(self._hide_after_id)
                except Exception:
                    pass
                self._hide_after_id = None
            self._tip_win.withdraw()
            return

        # Debounce 100ms để tránh flicker khi di chuột qua ranh giới phần tử
        if self._hide_after_id:
            try:
                self.after_cancel(self._hide_after_id)
            except Exception:
                pass
        self._hide_after_id = self.after(100, lambda: (self._tip_win.withdraw(), setattr(self, "_hide_after_id", None)))

    # ---------------------------------------------------------------------
    # KPI + DATA
    # ---------------------------------------------------------------------

    def _kpi_card(self, parent, col, title, value):
        card = ctk.CTkFrame(parent)
        card.grid(row=0, column=col, padx=8, pady=8, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, text_color="#9ca3af").grid(
            row=0, column=0, padx=12, pady=(10, 2), sticky="w"
        )
        ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=1, column=0, padx=12, pady=(0, 10), sticky="w"
        )

    def _resolve_color(self, color):
        """
        customtkinter có thể trả tuple/list màu [light, dark]; tkinter không hiểu.
        Chọn đúng màu theo appearance mode để dùng cho Canvas/outline.
        """
        if isinstance(color, (tuple, list)) and len(color) >= 2:
            return color[0] if ctk.get_appearance_mode() == "Light" else color[1]
        return color

    def _load_or_build(self) -> Dict[str, Any]:
        try:
            if os.path.exists(_SAMPLE_FILE):
                with open(_SAMPLE_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass

        rnd = random.Random(dt.date.today().toordinal())
        bars = [rnd.randint(3, 20) for _ in range(12)]
        line = [max(1, b - rnd.randint(0, 4)) for b in bars]
        now = dt.datetime.now().replace(microsecond=0)
        jobs = []
        for _ in range(18):
            ts = now - dt.timedelta(minutes=rnd.randint(5, 600))
            jobs.append(
                {
                    "when": ts.strftime("%Y-%m-%d %H:%M:%S"),
                    "db": f"DB_{rnd.randint(1,5)}",
                    "type": rnd.choice(["FULL", "DIFF", "LOG"]),
                    "status": rnd.choice(["OK", "OK", "OK", "FAIL"]),
                    "size": f"{rnd.randint(50, 900)} MB",
                }
            )
        return {
            "cards": {
                "databases": rnd.randint(2, 12),
                "backups_24h": sum(bars[-4:]),
                "failures_7d": rnd.randint(0, 3),
                "storage_used": f"{rnd.randint(40, 260)} GB",
            },
            "bar_series": bars,
            "line_series": line,
            "recent_jobs": sorted(jobs, key=lambda j: j["when"], reverse=True),
        }
