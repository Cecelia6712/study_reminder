"""学习提醒助手（Study Reminder）

功能：
    1. 课表管理（每行“周几|课程名|时间”）；
    2. 期末复习 / 考研复习进度管理（进度条 + 增减改删）；
    3. 每日日记（按日期保存，可前后翻页）；
    4. 设置每日提醒时间（支持错过补弹、强制置顶），到点自动弹出置顶的提醒窗口；
    5. 断电保护：无论是课表还是日记，停止输入 1 秒后自动落盘保存。

运行方式：
    python study_reminder.py

数据文件：
    与本脚本同目录的 study_data.json（UTF-8，indent=2，ensure_ascii=False）

依赖：
    仅使用 Python 3 标准库（tkinter / json / os / datetime）。
"""

import copy
import datetime
import json
import os
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

# ---------------------------------------------------------------------------
# 常量与数据读写
# ---------------------------------------------------------------------------

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(APP_DIR, "study_data.json")

WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

DEFAULT_DATA = {
    "enable_reminder": True,
    "remind_time": "08:00,12:00,18:00",
    "last_reminded": "",
    "courses": "",
    "final_exams": [],
    "kaoyan": [],
    "diary": {},
}


def _to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_review_list(items):
    result = []
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        total = _to_int(item.get("total", 0), 0)
        if total < 0:
            total = 0
        done = _to_int(item.get("done", 0), 0)
        done = max(0, min(done, total))
        result.append({
            "name": str(item.get("name", "")).strip() or "未命名",
            "done": done,
            "total": total,
        })
    return result


def load_data(path=DATA_FILE):
    raw = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
    if not isinstance(raw, dict):
        raw = {}

    data = {}
    for key, default in DEFAULT_DATA.items():
        if key in raw:
            data[key] = raw[key]
        else:
            data[key] = copy.deepcopy(default)

    if not isinstance(data.get("remind_time"), str) or not data["remind_time"]:
        data["remind_time"] = ""
    if not isinstance(data.get("last_reminded"), str):
        data["last_reminded"] = ""
    if not isinstance(data.get("courses"), str):
        data["courses"] = ""
    if not isinstance(data.get("diary"), dict):
        data["diary"] = {}
    if not isinstance(data.get("enable_reminder"), bool):
        data["enable_reminder"] = True
        
    data["final_exams"] = _normalize_review_list(data.get("final_exams"))
    data["kaoyan"] = _normalize_review_list(data.get("kaoyan"))
    return data


def save_data(data, path=DATA_FILE, parent=None):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as exc:
        messagebox.showerror("保存失败", "无法写入数据文件：\n%s\n%s" % (path, exc), parent=parent)
        return False


def normalize_weekday(text):
    day = (text or "").strip()
    day = day.replace("星期", "周")
    if day == "周天":
        day = "周日"
    return day


# ---------------------------------------------------------------------------
# 通用滚动容器
# ---------------------------------------------------------------------------

class ScrollFrame(ttk.Frame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)

        self.body = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.body, anchor="nw")

        self.body.bind("<Configure>", self._on_body_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_body_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self._win, width=event.width)


# ---------------------------------------------------------------------------
# 课表页
# ---------------------------------------------------------------------------

class CoursePage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app

        ttk.Label(self, text="每行格式：周几|课程名|时间\n例如：周一|高等数学|8:00-9:40",
                  justify="left", foreground="gray").pack(anchor="w")

        text_wrap = ttk.Frame(self)
        text_wrap.pack(fill="both", expand=True, pady=6)
        self.text = tk.Text(text_wrap, wrap="none", height=20, undo=True)
        vsb = ttk.Scrollbar(text_wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.insert("1.0", app.data.get("courses", ""))

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="保存课表", command=self.on_save_clicked).pack(side="left")
        self.tip = ttk.Label(bar, text="", foreground="gray")
        self.tip.pack(side="left", padx=8)

        self.text.bind("<KeyRelease>", self._on_text_change)

    def _on_text_change(self, event=None):
        self.app.data["courses"] = self.text.get("1.0", "end-1c")
        self.app.schedule_auto_save()

    def on_save_clicked(self):
        self.save_courses()
        self.tip.config(text="已保存 ✓")

    def save_courses(self, silent=False):
        try:
            content = self.text.get("1.0", "end-1c")
        except tk.TclError:
            return
        self.app.data["courses"] = content
        self.app.save()
        if not silent:
            self.tip.config(text="已保存 ✓")


# ---------------------------------------------------------------------------
# 复习进度页（期末 / 考研共用）
# ---------------------------------------------------------------------------

class ReviewPage(ttk.Frame):
    def __init__(self, master, app, data_key):
        super().__init__(master, padding=8)
        self.app = app
        self.data_key = data_key
        self.rows = []

        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="＋ 添加科目", command=self.add_subject).pack(side="left")
        self.summary = ttk.Label(top, text="", foreground="gray")
        self.summary.pack(side="right")

        self.scroll = ScrollFrame(self)
        self.scroll.pack(fill="both", expand=True, pady=(8, 0))

        self.refresh()

    def items(self):
        return self.app.data[self.data_key]

    def refresh(self):
        for child in self.scroll.body.winfo_children():
            child.destroy()
        self.rows = []

        items = self.items()
        if not items:
            ttk.Label(self.scroll.body, text="（暂无科目，点击上方按钮添加）",
                      foreground="gray").pack(anchor="w", pady=12)
        else:
            for idx, item in enumerate(items):
                self._build_row(idx, item)
        self.refresh_summary()

    def _build_row(self, idx, item):
        row = ttk.Frame(self.scroll.body)
        row.pack(fill="x", pady=4)

        line1 = ttk.Frame(row)
        line1.pack(fill="x")
        name_var = tk.StringVar(value=item.get("name", ""))
        ttk.Label(line1, textvariable=name_var, font=("", 10, "bold"),
                  anchor="w").pack(side="left", fill="x", expand=True)
        count_var = tk.StringVar()
        ttk.Label(line1, textvariable=count_var, anchor="e").pack(side="right")

        line2 = ttk.Frame(row)
        line2.pack(fill="x", pady=(3, 0))
        bar = ttk.Progressbar(line2, maximum=100, value=0)
        bar.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(line2, text="＋1", width=4, command=lambda i=idx: self.change(i, 1)).pack(side="left", padx=1)
        ttk.Button(line2, text="－1", width=4, command=lambda i=idx: self.change(i, -1)).pack(side="left", padx=1)
        ttk.Button(line2, text="改", width=3, command=lambda i=idx: self.edit(i)).pack(side="left", padx=1)
        ttk.Button(line2, text="删", width=3, command=lambda i=idx: self.delete(i)).pack(side="left", padx=1)

        self.rows.append({"bar": bar, "count": count_var, "name": name_var})
        self._update_row(idx)

    def _update_row(self, idx):
        items = self.items()
        if idx < 0 or idx >= len(items) or idx >= len(self.rows):
            return
        item = items[idx]
        total = max(0, _to_int(item.get("total", 0)))
        done = max(0, min(_to_int(item.get("done", 0)), total))
        percent = (done / total * 100.0) if total > 0 else 0.0
        row = self.rows[idx]
        try:
            row["bar"].config(value=percent)
            row["count"].set("%d/%d" % (done, total))
        except tk.TclError:
            pass

    def update_row(self, idx):
        self._update_row(idx)

    def refresh_summary(self):
        items = self.items()
        total_all = sum(max(0, _to_int(i.get("total", 0))) for i in items)
        done_all = sum(_to_int(i.get("done", 0)) for i in items)
        self.summary.config(text="共 %d 科 · 累计 %d/%d" % (len(items), done_all, total_all))

    def add_subject(self):
        name = simpledialog.askstring("添加科目", "科目名称：", parent=self.app.root)
        if not name: return
        name = name.strip()
        if not name: return
        total = simpledialog.askinteger("添加科目", "总任务量（正整数）：", parent=self.app.root, initialvalue=10, minvalue=1)
        if total is None: return
        self.items().append({"name": name, "done": 0, "total": int(total)})
        self.app.save()
        self.refresh()

    def change(self, idx, delta):
        items = self.items()
        if idx < 0 or idx >= len(items): return
        item = items[idx]
        total = max(0, _to_int(item.get("total", 0)))
        old = _to_int(item.get("done", 0))
        new = max(0, min(old + delta, total))
        if new == old: return
        item["done"] = new
        self.app.save()
        self._update_row(idx)
        self.refresh_summary()
        self.app.refresh_reminder()

    def edit(self, idx):
        items = self.items()
        if idx < 0 or idx >= len(items): return
        item = items[idx]

        name = simpledialog.askstring("修改科目", "科目名称：", parent=self.app.root, initialvalue=item.get("name", ""))
        if name is None: return
        name = name.strip()
        if not name: return

        total = simpledialog.askinteger("修改科目", "总任务量（正整数）：", parent=self.app.root, initialvalue=max(1, _to_int(item.get("total", 10), 10)), minvalue=1)
        if total is None: return

        done = simpledialog.askinteger("修改科目", "已完成：", parent=self.app.root, initialvalue=_to_int(item.get("done", 0)), minvalue=0, maxvalue=int(total))
        if done is None: return

        item["name"] = name
        item["total"] = int(total)
        item["done"] = max(0, min(int(done), int(total)))
        self.app.save()
        self.refresh()
        self.app.refresh_reminder()

    def delete(self, idx):
        items = self.items()
        if idx < 0 or idx >= len(items): return
        name = items[idx].get("name", "")
        if not messagebox.askyesno("删除确认", "确定要删除科目「%s」吗？" % name, parent=self.app.root): return
        items.pop(idx)
        self.app.save()
        self.refresh()
        self.app.refresh_reminder()


# ---------------------------------------------------------------------------
# 日记页
# ---------------------------------------------------------------------------

class DiaryPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self.current = datetime.date.today()

        bar = ttk.Frame(self)
        bar.pack(fill="x")
        ttk.Button(bar, text="◀", width=3, command=lambda: self.shift(-1)).pack(side="left")
        self.date_lbl = ttk.Label(bar, text="", anchor="center", font=("", 11, "bold"))
        self.date_lbl.pack(side="left", fill="x", expand=True)
        ttk.Button(bar, text="▶", width=3, command=lambda: self.shift(1)).pack(side="left")
        ttk.Button(bar, text="今天", width=6, command=self.goto_today).pack(side="right")

        self.text = tk.Text(self, wrap="word", undo=True)
        self.text.pack(fill="both", expand=True, pady=8)

        foot = ttk.Frame(self)
        foot.pack(fill="x")
        ttk.Button(foot, text="保存日记", command=self.on_save_clicked).pack(side="left")
        self.tip = ttk.Label(foot, text="", foreground="gray")
        self.tip.pack(side="left", padx=8)

        self.text.bind("<KeyRelease>", self._on_text_change)
        self.load_current()

    def date_key(self, date_obj=None):
        return (date_obj or self.current).strftime("%Y-%m-%d")

    def _on_text_change(self, event=None):
        content = self.text.get("1.0", "end-1c")
        key = self.date_key()
        if content.strip() == "":
            self.app.data["diary"].pop(key, None)
        else:
            self.app.data["diary"][key] = content
        self.app.schedule_auto_save()

    def load_current(self):
        key = self.date_key()
        self.date_lbl.config(text="%s  %s" % (key, WEEKDAY_NAMES[self.current.weekday()]))
        try:
            self.text.delete("1.0", "end")
            self.text.insert("1.0", self.app.data["diary"].get(key, ""))
            self.text.edit_reset()
        except tk.TclError:
            pass

    def save_current(self, show_tip=False):
        key = self.date_key()
        try:
            content = self.text.get("1.0", "end-1c")
        except tk.TclError:
            return
        diary = self.app.data["diary"]
        if content.strip() == "":
            diary.pop(key, None)
        else:
            diary[key] = content
        self.app.save()
        if show_tip:
            self.tip.config(text="已保存 " + datetime.datetime.now().strftime("%H:%M:%S"))

    def sync_today(self, content):
        if self.current != datetime.date.today(): return
        try:
            self.text.delete("1.0", "end")
            if content: self.text.insert("1.0", content)
        except tk.TclError:
            pass

    def on_save_clicked(self):
        self.save_current(show_tip=True)

    def shift(self, days):
        self.save_current()
        self.current += datetime.timedelta(days=days)
        self.load_current()
        self.tip.config(text="")

    def goto_today(self):
        self.save_current()
        self.current = datetime.date.today()
        self.load_current()
        self.tip.config(text="")


# ---------------------------------------------------------------------------
# 设置页
# ---------------------------------------------------------------------------

class SettingsPage(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=12)
        self.app = app

        self.enable_var = tk.BooleanVar(value=app.data.get("enable_reminder", True))
        ttk.Checkbutton(self, text="启用每日定时弹窗提醒", variable=self.enable_var, command=self.save_settings).pack(anchor="w", pady=(0, 10))

        ttk.Label(self, text="提醒时间（多个时间用英文逗号隔开，支持留空）：").pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=6)
        self.time_var = tk.StringVar(value=app.data.get("remind_time", "08:00,12:00,18:00"))
        ttk.Entry(row, textvariable=self.time_var, width=30).pack(side="left")
        ttk.Button(row, text="保存", command=self.save_settings).pack(side="left", padx=6)

        self.tip = ttk.Label(self, text="", foreground="gray")
        self.tip.pack(anchor="w")

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=12)
        ttk.Button(self, text="立即预览提醒弹窗", command=self.app.show_reminder).pack(anchor="w")

        note = ("提示：\n"
                "· 取消勾选上方开关，程序将不再定时自动弹窗。\n"
                "· 如果休眠或锁屏错过了时间，唤醒后会自动补弹。\n"
                "· 弹窗必须点击“我知道了”才能关闭。")
        ttk.Label(self, text=note, foreground="gray", justify="left").pack(anchor="w", pady=12)

    def save_settings(self):
        enable = self.enable_var.get()
        raw = self.time_var.get().strip()
        valid_times = []
        if raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            for part in parts:
                try:
                    parsed = datetime.datetime.strptime(part, "%H:%M")
                    valid_times.append("%02d:%02d" % (parsed.hour, parsed.minute))
                except ValueError:
                    messagebox.showerror("格式错误", "请输入正确的时间格式，用英文逗号隔开，例如 08:00,12:00,18:00", parent=self.app.root)
                    return
            valid_times = list(dict.fromkeys(valid_times))
            
        value = ",".join(valid_times)
        self.app.data["enable_reminder"] = enable
        self.app.data["remind_time"] = value
        self.time_var.set(value)
        self.app.save()
        self.tip.config(text="已保存 ✓")


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------

class StudyReminderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("学习提醒助手")
        self.root.geometry("500x640")
        self.root.minsize(460, 560)

        self.data = load_data()
        self.reminder_win = None
        self.reminder_diary_draft = None
        self._save_job = None

        self._build_ui()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(20000, self.tick)

    def _build_ui(self):
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=4, pady=4)

        self.course_page = CoursePage(notebook, self)
        self.final_page = ReviewPage(notebook, self, "final_exams")
        self.kaoyan_page = ReviewPage(notebook, self, "kaoyan")
        self.diary_page = DiaryPage(notebook, self)
        self.settings_page = SettingsPage(notebook, self)

        notebook.add(self.course_page, text="课表")
        notebook.add(self.final_page, text="期末复习")
        notebook.add(self.kaoyan_page, text="考研复习")
        notebook.add(self.diary_page, text="日记")
        notebook.add(self.settings_page, text="设置")

    def save(self):
        return save_data(self.data, DATA_FILE, self.root)

    def schedule_auto_save(self):
        if self._save_job is not None:
            self.root.after_cancel(self._save_job)
        self._save_job = self.root.after(1000, self._perform_auto_save)

    def _perform_auto_save(self):
        self._save_job = None
        self.save()

    def courses_for_weekday(self, weekday_index):
        result = []
        raw = self.data.get("courses", "")
        if not isinstance(raw, str): return result
        target = WEEKDAY_NAMES[weekday_index]
        for line in raw.splitlines():
            line = line.strip()
            if not line: continue
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 3: continue
            if normalize_weekday(parts[0]) != target: continue
            result.append("%s  %s" % (parts[1], parts[2]))
        return result

    def show_reminder(self):
        if self.reminder_win is not None:
            try:
                if self.reminder_win.winfo_exists():
                    self.reminder_win.deiconify()
                    self.reminder_win.attributes("-topmost", True)
                    self.reminder_win.lift()
                    self.reminder_win.focus_force()
                    return
            except tk.TclError:
                pass
            self.reminder_win = None

        self.reminder_diary_draft = None

        win = tk.Toplevel(self.root)
        current_time = datetime.datetime.now().strftime("%H:%M")
        win.title("每日学习提醒 - " + current_time)
        win.attributes("-topmost", True)
        width, height = 530, 680
        try:
            x = max(0, (win.winfo_screenwidth() - width) // 2)
            y = max(0, (win.winfo_screenheight() - height) // 2)
            win.geometry("%dx%d+%d+%d" % (width, height, x, y))
        except tk.TclError:
            win.geometry("%dx%d" % (width, height))
            
        win.protocol("WM_DELETE_WINDOW", self._on_close_click_attempt)
        self.reminder_win = win

        self._rebuild_reminder(win)
        try:
            win.lift()
            win.focus_force()
        except tk.TclError:
            pass

    def _on_close_click_attempt(self):
        if self.reminder_win is not None:
            messagebox.showwarning("无法关闭", "请点击下方的【我知道了】按钮来关闭弹窗。", parent=self.reminder_win)

    def close_reminder(self):
        win = self.reminder_win
        self._auto_save_reminder_diary()
        self.reminder_win = None
        self.reminder_diary_draft = None
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass

    def _section_title(self, win, text):
        frame = ttk.Frame(win)
        frame.pack(fill="x", padx=12, pady=(10, 2))
        ttk.Label(frame, text=text, font=("", 11, "bold")).pack(anchor="w")
        ttk.Separator(win, orient="horizontal").pack(fill="x", padx=12)

    def _rebuild_reminder(self, win):
        try:
            for child in win.winfo_children():
                child.destroy()

            today = datetime.date.today()
            today_key = today.strftime("%Y-%m-%d")

            bottom = ttk.Frame(win)
            bottom.pack(side="bottom", fill="x", pady=10)
            ttk.Button(bottom, text="我知道了", command=self.close_reminder).pack()

            ttk.Label(win, text="%s  %s" % (today_key, WEEKDAY_NAMES[today.weekday()]), font=("", 14, "bold")).pack(pady=(12, 4))

            self._section_title(win, "📚 今日课程")
            courses = self.courses_for_weekday(today.weekday())
            if courses:
                for line in courses:
                    ttk.Label(win, text="   " + line, anchor="w").pack(fill="x", padx=18)
            else:
                ttk.Label(win, text="   今天没有课", foreground="gray").pack(anchor="w", padx=18)

            self._section_title(win, "📝 期末复习进度")
            self._build_reminder_review(win, "final_exams")

            self._section_title(win, "🎯 考研复习进度")
            self._build_reminder_review(win, "kaoyan")

            self._section_title(win, "✍️ 今日日记")
            self._build_reminder_diary(win, today_key)

        except tk.TclError:
            pass

    def _build_reminder_review(self, win, data_key):
        items = self.data.get(data_key, [])
        if not items:
            ttk.Label(win, text="   暂无科目", foreground="gray").pack(anchor="w", padx=18, pady=2)
            return
        for idx, item in enumerate(items):
            row = ttk.Frame(win)
            row.pack(fill="x", padx=18, pady=2)
            total = max(0, _to_int(item.get("total", 0)))
            done = max(0, min(_to_int(item.get("done", 0)), total))
            percent = (done / total * 100.0) if total > 0 else 0.0

            # 将 width=10 改为了 width=16，防止长名字被截断
            ttk.Label(row, text=item.get("name", ""), width=16, anchor="w").pack(side="left")
            ttk.Progressbar(row, maximum=100, value=percent, length=130).pack(side="left", padx=4)
            ttk.Label(row, text="%d/%d" % (done, total), width=8).pack(side="left")
            ttk.Button(row, text="+1", width=3, command=lambda k=data_key, i=idx: self.reminder_plus(k, i)).pack(side="left", padx=4)

    def _build_reminder_diary(self, win, today_key):
        frame = ttk.Frame(win)
        frame.pack(fill="both", expand=True, padx=18, pady=(4, 0))

        text = tk.Text(frame, height=4, wrap="word")
        text.pack(fill="both", expand=True)

        draft = self.reminder_diary_draft
        if draft is None:
            draft = self.data["diary"].get(today_key, "")
            self.reminder_diary_draft = draft
        try:
            text.insert("1.0", draft)
            text.edit_modified(False)
        except tk.TclError:
            pass
        text.bind("<<Modified>>", lambda e, t=text: self._on_reminder_modified(t))

        bar = ttk.Frame(win)
        bar.pack(fill="x", padx=18, pady=6)
        tip = ttk.Label(bar, text="", foreground="green")
        ttk.Button(bar, text="保存日记", command=lambda: self._save_reminder_diary(text, tip)).pack(side="left")
        tip.pack(side="left", padx=8)

    def _on_reminder_modified(self, text):
        try:
            if not text.edit_modified(): return
            content = text.get("1.0", "end-1c")
            self.reminder_diary_draft = content
            today_key = datetime.date.today().strftime("%Y-%m-%d")
            diary = self.data["diary"]
            if content.strip() == "":
                diary.pop(today_key, None)
            else:
                diary[today_key] = content
            self.schedule_auto_save()
            text.edit_modified(False)
        except tk.TclError:
            pass

    def _write_diary(self, content):
        today_key = datetime.date.today().strftime("%Y-%m-%d")
        diary = self.data["diary"]
        if content.strip() == "":
            diary.pop(today_key, None)
        else:
            diary[today_key] = content
        self.save()

    def _save_reminder_diary(self, text, tip_label):
        try:
            content = text.get("1.0", "end-1c")
        except tk.TclError:
            return
        self.reminder_diary_draft = content
        self._write_diary(content)
        try:
            tip_label.config(text="已保存 ✓")
        except tk.TclError:
            pass
        self.diary_page.sync_today(content)

    def _auto_save_reminder_diary(self):
        if self.reminder_diary_draft is None: return
        self._write_diary(self.reminder_diary_draft)
        self.diary_page.sync_today(self.reminder_diary_draft)

    def reminder_plus(self, data_key, idx):
        items = self.data.get(data_key, [])
        if idx < 0 or idx >= len(items): return
        item = items[idx]
        total = max(0, _to_int(item.get("total", 0)))
        done = _to_int(item.get("done", 0)) + 1
        if done > total: done = total
        if done == _to_int(item.get("done", 0)): return
        item["done"] = done
        self.save()
        page = self.final_page if data_key == "final_exams" else self.kaoyan_page
        page.update_row(idx)
        page.refresh_summary()
        self.root.after_idle(self.refresh_reminder)

    def refresh_reminder(self):
        if self.reminder_win is None: return
        try:
            if self.reminder_win.winfo_exists():
                self._rebuild_reminder(self.reminder_win)
            else:
                self.reminder_win = None
        except tk.TclError:
            self.reminder_win = None

    def tick(self):
        try:
            if not self.data.get("enable_reminder", True): return
            now = datetime.datetime.now()
            today_key = now.strftime("%Y-%m-%d")
            current_time = now.strftime("%H:%M")
            
            raw_times = str(self.data.get("remind_time", "")).strip()
            if not raw_times: return
            remind_times = [t.strip() for t in raw_times.split(",") if t.strip()]
            remind_times.sort()

            target_record = None
            for t in remind_times:
                if current_time >= t:
                    target_record = "%s %s" % (today_key, t)
                else:
                    break

            if target_record and self.data.get("last_reminded") != target_record:
                self.data["last_reminded"] = target_record
                self.save()
                self.show_reminder()

            if self.reminder_win is not None:
                try:
                    if self.reminder_win.winfo_exists():
                        self.reminder_win.attributes("-topmost", True)
                        self.reminder_win.lift()
                except tk.TclError:
                    pass

        except Exception:
            pass
        finally:
            try:
                self.root.after(20000, self.tick)
            except tk.TclError:
                pass

    def on_close(self):
        try: self.course_page.save_courses(silent=True)
        except Exception: pass
        try: self.diary_page.save_current()
        except Exception: pass
        self.save()
        try: self.root.destroy()
        except tk.TclError: pass


def main():
    root = tk.Tk()
    StudyReminderApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()