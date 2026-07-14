import webview
import asyncio
import threading
import json
import os
import sys
import time
import logging
import webbrowser
import tkinter as tk
from tkinter import filedialog
from logging.handlers import RotatingFileHandler
from datetime import datetime, timedelta
from Get_Cookies import Recent_Login, Get_New_Cookies
from Get_Record import schedule_monitoring, run_spider, merge_records

def _safe_path(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)

log_file = _safe_path("app.log")
handler = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=2, encoding='utf-8')
handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(handler)
logging.getLogger().setLevel(logging.INFO)

class StreamToLogger:
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())
    def flush(self):
        pass

sys.stdout = StreamToLogger(logging.getLogger(), logging.INFO)

DIFFICULTY_COLORS = {
    "入门": "#FF4A5A",
    "普及−": "#F29422",
    "普及": "#FFBC00",
    "普及+/提高−": "#48C038",
    "提高": "#20C0C8",
    "提高+/省选−": "#3698E0",
    "省选/NOI−": "#9955DD",
    "NOI/NOI+/CTS": "#1A2860",
    "暂无评定": "#bfbfbf",
    "未知": "#666666"
}
DEFAULT_COLOR = "#bfbfbf"

DIFFICULTY_LEVELS = {
    "入门": 0,
    "普及−": 1,
    "普及": 2,
    "普及+/提高−": 3,
    "提高": 4,
    "提高+/省选−": 5,
    "省选/NOI−": 6,
    "NOI/NOI+/CTS": 7,
    "暂无评定": -1,
    "未知": -2
}

TOAST_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            margin: 0; padding: 20px 15px 15px 15px; overflow: hidden;
            background-color: #fff; font-family: 'Segoe UI', sans-serif;
            border-left: 8px solid {color};
            display: flex; flex-direction: column; justify-content: center;
            height: 100vh; padding-left: 15px; box-sizing: border-box;
            user-select: none; cursor: default; position: relative;
        }}
        .header {{ font-size: 12px; color: #888; margin-bottom: 5px; display: flex; justify-content: space-between; padding-right: 30px;}}
        .user {{ font-weight: bold; color: #333; font-size: 14px; }}
        .content {{ font-size: 13px; color: #444; margin-bottom: 8px; line-height: 1.4; padding-right: 10px;}}
        .problem-id {{ font-weight: bold; color: #000; }}
        .badge {{
            display: inline-block; background-color: {color}; color: white;
            padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;
        }}
        .toast-close-btn {{
            position: absolute;
            top: -12px; right: -12px;
            width: 26px; height: 26px;
            border-radius: 50%;
            background: #fff;
            border: 2px solid #ccc;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 18px;
            color: #666;
            z-index: 10;
            line-height: 1;
        }}
        .toast-close-btn:hover {{ background: #f0f0f0; }}
    </style>
</head>
<body>
    <div class="toast-close-btn" onclick="closeMe()">×</div>
    <div class="header">
        <span class="user">{user_name}</span>
        <span>{time_str}</span>
    </div>
    <div class="content">
        提交了 <span class="problem-id">{problem_number}</span><br>
        {problem_name}
    </div>
    <div>
        <span class="badge">{difficulty}</span>
    </div>
    <script>
        function closeMe() {{ pywebview.api.close_toast(); }}
        setTimeout(closeMe, 8000);
    </script>
</body>
</html>"""

class ToastApi:
    def __init__(self, window):
        self.window = window
    def close_toast(self):
        self.window.destroy()

class Api:
    def __init__(self):
        self._window = None
        self.loop = None
        self.monitor_task = None
        self.current_username = None
        self.notified_records = set()
        self.monitoring_active = False
        self.monitoring_paused = False
        self.pause_check_lock = threading.Lock()

    def set_window(self, window):
        self._window = window

    def init_check(self):
        user = Recent_Login()
        if user == "Not_Found_User":
            return {"status": "require_login"}
        else:
            self.current_username = user
            return {"status": "success", "username": user}

    def attempt_login(self, username, password):
        try:
            success = asyncio.run(Get_New_Cookies(username, password))
            if success:
                self.current_username = username
                return {"status": "success", "username": username}
            else:
                return {"status": "fail", "message": "用户名或密码错误"}
        except Exception as e:
            logging.error(f"登录异常: {e}")
            return {"status": "fail", "message": str(e)}

    def is_paused(self):
        with self.pause_check_lock:
            return self.monitoring_paused

    def toggle_monitoring_pause(self):
        with self.pause_check_lock:
            self.monitoring_paused = not self.monitoring_paused
            new_state = self.monitoring_paused
        print(f"[系统] 监控{'已暂停' if new_state else '已恢复'}")
        return {"status": "success", "paused": new_state}

    def get_monitor_status(self):
        with self.pause_check_lock:
            return {"status": "success", "paused": self.monitoring_paused}

    def start_monitoring(self, username):
        print(f"[系统] 准备启动监控: {username}")
        self.stop_monitoring()
        self.monitoring_active = True
        self.monitoring_paused = False

        def crawler_thread_target():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            self.loop = new_loop
            self.monitor_task = new_loop.create_task(
                schedule_monitoring(username, 0.5, pause_check=self.is_paused)
            )
            try:
                new_loop.run_until_complete(self.monitor_task)
            except:
                pass
            finally:
                if new_loop.is_running():
                    new_loop.stop()
                new_loop.close()

        def notification_checker_target():
            print("[系统] 弹窗检测服务已启动")
            while self.monitoring_active:
                try:
                    self.check_and_notify()
                except Exception as e:
                    print(f"[错误] 检测通知出错: {e}")
                time.sleep(10)

        threading.Thread(target=crawler_thread_target, daemon=True).start()
        threading.Thread(target=notification_checker_target, daemon=True).start()

    def stop_monitoring(self):
        self.monitoring_active = False
        if self.loop and self.monitor_task:
            try:
                self.loop.call_soon_threadsafe(self.monitor_task.cancel)
            except RuntimeError:
                pass
            self.loop = None
            self.monitor_task = None

    def _load_problem_map(self):
        path = _safe_path('problem_list.json')
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            if isinstance(raw, dict) and 'data' in raw:
                return raw['data']
            elif isinstance(raw, dict):
                return raw
            else:
                return {}
        except Exception as e:
            print(f"加载 problem_list.json 出错: {e}")
            return {}

    def check_and_notify(self):
        problem_map = self._load_problem_map()
        users_data = self._load_json('user_records.json')
        if not users_data:
            return
        now = datetime.now()
        for user in users_data:
            uid = user.get('user_id')
            uname = user.get('user_name')
            for record in user.get('records', []):
                p_num = record.get('problem_number')
                p_name = record.get('problem_name')
                post_date_str = record.get('post_date')
                record_id = f"{uid}_{p_num}_{post_date_str}"
                if record_id in self.notified_records:
                    continue
                try:
                    record_time = datetime.strptime(post_date_str, "%Y-%m-%d %H:%M:%S")
                    if now - record_time < timedelta(minutes=10):
                        self.notified_records.add(record_id)
                        difficulty = problem_map.get(p_num, "未知")
                        color = DIFFICULTY_COLORS.get(difficulty, DEFAULT_COLOR)
                        time_display = post_date_str.split(" ")[1]
                        self.show_desktop_toast(uname, p_num, p_name, time_display, difficulty, color)
                        notify_data = {
                            "user_name": uname, "problem_number": p_num, "problem_name": p_name,
                            "time_str": time_display, "difficulty": difficulty, "color": color
                        }
                        if self._window:
                            self._window.evaluate_js(f'createNotificationCard({json.dumps(notify_data)})')
                        time.sleep(1)
                except ValueError:
                    continue

    def show_desktop_toast(self, uname, p_num, p_name, t_str, diff, col):
        screens = webview.screens
        if not screens:
            return
        screen = screens[0]
        width, height = 300, 140
        x = int(screen.width - width - 20)
        y = int(screen.height - height - 60)
        html = TOAST_HTML_TEMPLATE.format(
            user_name=uname, problem_number=p_num, problem_name=p_name,
            time_str=t_str, difficulty=diff, color=col
        )
        toast = webview.create_window(
            title='Notification', html=html, width=width, height=height,
            x=x, y=y, frameless=True, on_top=True, resizable=False, focus=False
        )
        toast.expose(ToastApi(toast).close_toast)

    def _load_json(self, filename):
        path = _safe_path(filename)
        if not os.path.exists(path):
            return {} if 'list' in filename else []
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"加载 {filename} 出错: {e}")
            return {} if 'list' in filename else []

    def get_signature(self):
        if not self.current_username:
            return "后台自动抓取中。新提交将触发双重弹窗提醒。"
        path = _safe_path("signature.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and self.current_username in data:
                        return data[self.current_username]
            except:
                pass
        return "后台自动抓取中。新提交将触发双重弹窗提醒。"

    def update_signature(self, text):
        if not self.current_username:
            return {"status": "error", "message": "未登录"}
        path = _safe_path("signature.json")
        data = {}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except:
                data = {}
        if not isinstance(data, dict):
            data = {}
        data[self.current_username] = text
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def get_leaderboard_data(self, days, min_lv, max_lv, include_none):
        try:
            days = int(days)
            min_lv = int(min_lv)
            max_lv = int(max_lv)
            if isinstance(include_none, bool):
                include_none_flag = include_none
            else:
                include_none_flag = include_none.lower() == 'true'
        except Exception as e:
            return {"status": "error", "message": f"参数错误: {str(e)}"}

        # 获取当前用户的监控配置（包含备注）
        user_note_map = {}
        if self.current_username:
            try:
                raw_data = self._load_json('user_ids.json')
                if isinstance(raw_data, dict):
                    user_config = raw_data.get(self.current_username, [])
                    for item in user_config:
                        if isinstance(item, dict):
                            uid = str(item.get("id", ""))
                            note = item.get("note", "")
                            user_note_map[uid] = note
                        else:
                            user_note_map[str(item)] = ""
                elif isinstance(raw_data, list):
                    for uid in raw_data:
                        user_note_map[str(uid)] = ""
            except:
                pass

        monitor_user_ids = list(user_note_map.keys())
        users_data = self._load_json('user_records.json')
        problem_map = self._load_problem_map()
        now = datetime.now()
        leaderboard = []
        filter_by_time = (days > 0)
        start_date = None
        if filter_by_time:
            start_date = now - timedelta(days=days)

        for user in users_data:
            if str(user.get('user_id')) not in monitor_user_ids:
                continue
            valid_count = 0
            for record in user.get('records', []):
                if filter_by_time:
                    p_date_str = record.get('post_date')
                    try:
                        p_date = datetime.strptime(p_date_str, "%Y-%m-%d %H:%M:%S")
                        if p_date < start_date:
                            continue
                    except:
                        continue
                p_num = record.get('problem_number')
                difficulty = problem_map.get(p_num, "未知")
                level = DIFFICULTY_LEVELS.get(difficulty, -2)
                if level == -2:
                    if include_none_flag:
                        valid_count += 1
                elif level == -1:
                    if include_none_flag:
                        valid_count += 1
                else:
                    if min_lv <= level <= max_lv:
                        valid_count += 1
            if valid_count > 0:
                uid = str(user.get('user_id'))
                leaderboard.append({
                    "user_id": uid,
                    "user_name": user.get('user_name'),
                    "note": user_note_map.get(uid, ""),
                    "count": valid_count
                })

        leaderboard.sort(key=lambda x: x['count'], reverse=True)
        return {"status": "success", "data": leaderboard}

    def export_leaderboard_csv(self, days, min_lv, max_lv, include_none):
        res = self.get_leaderboard_data(days, min_lv, max_lv, include_none)
        if res["status"] != "success":
            return res
        import csv, io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["排名", "用户ID", "用户名", "备注", "通过数"])
        for idx, item in enumerate(res["data"], 1):
            writer.writerow([idx, item["user_id"], item["user_name"], item.get("note", ""), item["count"]])
        csv_content = output.getvalue()
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        file_path = filedialog.asksaveasfilename(
            parent=root,
            title="导出排行榜为 CSV",
            defaultextension=".csv",
            filetypes=[("CSV 文件", "*.csv"), ("所有文件", "*.*")],
            initialfile="leaderboard.csv"
        )
        root.destroy()
        if not file_path:
            return {"status": "cancelled", "message": "已取消导出"}
        try:
            with open(file_path, "w", encoding="utf-8-sig", newline="") as f:
                f.write(csv_content)
            logging.info(f"排行榜已导出至 {file_path}")
            return {"status": "success", "path": file_path}
        except Exception as e:
            logging.error(f"导出 CSV 失败: {e}")
            return {"status": "error", "message": str(e)}

    def get_user_records_page(self, uid, page, difficulty="", page_size=10):
        try:
            page = int(page)
            page_size = int(page_size)
        except (ValueError, TypeError):
            return {"status": "error", "message": "参数错误"}
        users_data = self._load_json('user_records.json')
        problem_map = self._load_problem_map()
        target_user = next((u for u in users_data if str(u.get('user_id')) == str(uid)), None)
        if not target_user:
            return {"status": "error", "message": "用户未找到"}
        all_records = target_user.get('records', [])
        if difficulty and not problem_map:
            logging.warning("题库数据缺失，无法按难度筛选，显示全部记录")
        elif difficulty and problem_map:
            if difficulty == "未知":
                all_records = [r for r in all_records if not problem_map.get(r['problem_number'])]
            else:
                all_records = [r for r in all_records if problem_map.get(r['problem_number']) == difficulty]
        total = len(all_records)
        start = (page - 1) * page_size
        end = start + page_size
        paged_records = all_records[start:end]
        processed_records = []
        for r in paged_records:
            p_num = r.get('problem_number')
            diff = problem_map.get(p_num, "未知")
            color = DIFFICULTY_COLORS.get(diff, DEFAULT_COLOR)
            r_copy = r.copy()
            r_copy['difficulty'] = diff
            r_copy['color'] = color
            processed_records.append(r_copy)
        return {
            "status": "success",
            "data": processed_records,
            "total": total,
            "user_name": target_user.get('user_name')
        }

    def get_monitor_config(self):
        if not self.current_username:
            return {"status": "error", "message": "User not found"}
        monitor_raw = []
        try:
            raw_data = self._load_json('user_ids.json')
            if isinstance(raw_data, list):
                monitor_raw = [{"id": str(x), "note": ""} for x in raw_data]
            elif isinstance(raw_data, dict):
                user_config = raw_data.get(self.current_username, [])
                if isinstance(user_config, list):
                    for item in user_config:
                        if isinstance(item, dict):
                            monitor_raw.append({"id": str(item.get("id", "")), "note": item.get("note", "")})
                        else:
                            monitor_raw.append({"id": str(item), "note": ""})
        except:
            pass
        users_records = self._load_json('user_records.json')
        id_name_map = {str(u['user_id']): u['user_name'] for u in users_records}
        enhanced_list = []
        for item in monitor_raw:
            uid = item["id"]
            name = id_name_map.get(uid, "未知用户")
            note = item.get("note", "")
            enhanced_list.append({"id": uid, "name": name, "note": note})
        return {"status": "success", "data": enhanced_list, "current_uid": self.current_username}

    def save_monitor_config(self, new_list):
        if not self.current_username:
            return {"status": "error", "message": "Auth failed"}
        path = _safe_path('user_ids.json')
        data = {}
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except:
                data = {}
        if isinstance(data, list):
            data = {}
        clean_list = [{"id": str(item["id"]), "note": item.get("note", "")} for item in new_list]
        data[self.current_username] = clean_list
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            return {"status": "error", "message": str(e)}
        print(f"[系统] 配置更新，重启监控...")
        self.start_monitoring(self.current_username)
        return {"status": "success"}

    def logout(self):
        self.stop_monitoring()
        path = _safe_path('cookies.json')
        cookies = []
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
            except:
                cookies = []
        if isinstance(cookies, list) and self.current_username:
            new_cookies = [c for c in cookies if c.get('user_name') != self.current_username]
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(new_cookies, f, ensure_ascii=False, indent=2)
            except:
                pass
        self.current_username = None
        return {"status": "logged_out"}

    def trigger_manual_monitoring(self):
        def run_once():
            try:
                logging.info("手动监控任务开始")
                with open(_safe_path('user_ids.json'), 'r') as f:
                    uid_data = json.load(f)
                user_config = uid_data.get(self.current_username, [])
                user_ids = [str(item["id"] if isinstance(item, dict) else item) for item in user_config]
                if not user_ids:
                    logging.warning("监控列表为空，跳过手动监控")
                    return
                with open(_safe_path('cookies.json'), 'r') as f:
                    cookies = json.load(f)
                login_user_id = None
                for c in cookies:
                    if c.get("user_name") == self.current_username:
                        login_user_id = c.get("user_id")
                        break
                if not login_user_id:
                    logging.error("找不到登录用户ID，无法执行手动监控")
                    return
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                new_records = loop.run_until_complete(
                    run_spider(login_user_id, user_ids, _safe_path('cookies.json'), _safe_path('user_records.json'))
                )
                loop.close()
                existing = []
                try:
                    with open(_safe_path('user_records.json'), 'r', encoding='utf-8') as f:
                        existing = json.load(f)
                except:
                    pass
                merged = merge_records(existing, new_records)
                with open(_safe_path('user_records.json'), 'w', encoding='utf-8') as f:
                    json.dump(merged, f, ensure_ascii=False, indent=2)
                logging.info("手动监控完成")
                if self._window:
                    self._window.evaluate_js('if(typeof loadLeaderboard === "function") loadLeaderboard();')
            except Exception as e:
                logging.error(f"手动监控出错: {e}")
        threading.Thread(target=run_once, daemon=True).start()
        return {"status": "started"}

    def get_logs(self, lines=200):
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                all_lines = f.readlines()
                return {"status": "success", "logs": all_lines[-lines:]}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def clear_logs(self):
        try:
            open(log_file, 'w').close()
            logging.info("日志已清空")
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def export_logs(self):
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        file_path = filedialog.asksaveasfilename(
            parent=root,
            title="导出日志",
            defaultextension=".log",
            filetypes=[("日志文件", "*.log"), ("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile="app.log"
        )
        root.destroy()
        if not file_path:
            return {"status": "cancelled", "message": "已取消导出"}
        try:
            with open(log_file, "r", encoding="utf-8") as src, open(file_path, "w", encoding="utf-8") as dst:
                dst.write(src.read())
            logging.info(f"日志已导出至 {file_path}")
            return {"status": "success", "path": file_path}
        except Exception as e:
            logging.error(f"导出日志失败: {e}")
            return {"status": "error", "message": str(e)}

    def open_problem_window(self, problem_id):
        try:
            webbrowser.open(f"https://www.luogu.com.cn/problem/{problem_id}")
            logging.info(f"已在默认浏览器中打开题目: {problem_id}")
        except Exception as e:
            logging.error(f"打开题目失败: {e}")

    def close_app(self):
        try:
            if self._window:
                self._window.destroy()
        except:
            pass
        os._exit(0)

if __name__ == '__main__':
    api = Api()
    window = webview.create_window(
        'Luogu Monitor Pro', 'web/index.html',
        width=980, height=800,
        resizable=False, js_api=api, frameless=True, easy_drag=True
    )
    api.set_window(window)
    webview.start(debug=False)
