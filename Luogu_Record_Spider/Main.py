import webview
import asyncio
import threading
import json
import os
import time
from datetime import datetime, timedelta
from Get_Cookies import Recent_Login, Get_New_Cookies
from Get_Record import schedule_monitoring

# ---------- 路径辅助函数 ----------
def _safe_path(filename):
    """返回脚本所在目录下的绝对路径"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)

DIFFICULTY_COLORS = {
    "入门": "#fe4c61",
    "普及−": "#f39c11",
    "普及/提高−": "#ffc116",
    "普及+/提高": "#53c41a",
    "提高+/省选": "#3498db",
    "省选/NOI−": "#9c3dcf",
    "NOI/NOI+/CTSC": "#0e1d69"
}
DEFAULT_COLOR = "#bfbfbf"

DIFFICULTY_LEVELS = {
    "入门": 0,
    "普及−": 1,
    "普及/提高−": 2,
    "普及+/提高": 3,
    "提高+/省选": 4,
    "省选/NOI−": 5,
    "NOI/NOI+/CTSC": 6
}

TOAST_HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{
            margin: 0; padding: 0; overflow: hidden;
            background-color: #fff; font-family: 'Segoe UI', sans-serif;
            border-left: 8px solid {color};
            display: flex; flex-direction: column; justify-content: center;
            height: 100vh; padding-left: 15px; box-sizing: border-box;
            user-select: none; cursor: default;
        }}
        .header {{ font-size: 12px; color: #888; margin-bottom: 5px; display: flex; justify-content: space-between; padding-right: 15px;}}
        .user {{ font-weight: bold; color: #333; font-size: 14px; }}
        .content {{ font-size: 13px; color: #444; margin-bottom: 8px; line-height: 1.4; padding-right: 10px;}}
        .problem-id {{ font-weight: bold; color: #000; }}
        .badge {{
            display: inline-block; background-color: {color}; color: white;
            padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold;
        }}
        .close-btn {{
            position: absolute; top: 5px; right: 8px; color: #ccc; cursor: pointer; font-size: 16px;
        }}
        .close-btn:hover {{ color: #000; }}
    </style>
</head>
<body>
    <div class="close-btn" onclick="closeMe()">×</div>
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
</html>
"""

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
        success = asyncio.run(Get_New_Cookies(username, password))
        if success:
            self.current_username = username
            return {"status": "success", "username": username}
        else:
            return {"status": "fail", "message": "用户名或密码错误"}

    def start_monitoring(self, username):
        print(f"[系统] 准备启动监控: {username}")
        self.stop_monitoring()
        self.monitoring_active = True

        def crawler_thread_target():
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            self.loop = new_loop
            self.monitor_task = new_loop.create_task(schedule_monitoring(username, 0.5))
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

        t1 = threading.Thread(target=crawler_thread_target, daemon=True)
        t1.start()
        t2 = threading.Thread(target=notification_checker_target, daemon=True)
        t2.start()

    def stop_monitoring(self):
        self.monitoring_active = False
        if self.loop and self.monitor_task:
            try:
                self.loop.call_soon_threadsafe(self.monitor_task.cancel)
            except RuntimeError:
                pass
            self.loop = None
            self.monitor_task = None

    def check_and_notify(self):
        problem_map = self._load_json('problem_list.json')
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

    # ---------- 排行榜：只显示监控名单中的用户 ----------
    def get_leaderboard_data(self, days, min_lv, max_lv):
        try:
            days = int(days)
            min_lv = int(min_lv)
            max_lv = int(max_lv)
        except:
            return {"status": "error", "message": "参数错误"}

        # 读取当前监控名单（用户名 → 用户ID列表）
        monitor_user_ids = []
        if self.current_username:
            try:
                user_ids_data = self._load_json('user_ids.json')
                monitor_user_ids = user_ids_data.get(self.current_username, [])
                # 确保所有 ID 为字符串，便于比较
                monitor_user_ids = [str(uid) for uid in monitor_user_ids]
            except:
                pass

        users_data = self._load_json('user_records.json')
        problem_map = self._load_json('problem_list.json')
        now = datetime.now()
        leaderboard = []

        filter_by_time = (days > 0)
        start_date = None
        if filter_by_time:
            start_date = now - timedelta(days=days)

        for user in users_data:
            # 只统计监控名单中的用户（保留本地数据不删除）
            if str(user.get('user_id')) not in monitor_user_ids:
                continue

            valid_count = 0
            uid = user.get('user_id')
            uname = user.get('user_name')
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
                level = DIFFICULTY_LEVELS.get(difficulty, -1)
                if level != -1 and min_lv <= level <= max_lv:
                    valid_count += 1
            if valid_count > 0:
                leaderboard.append({
                    "user_id": uid,
                    "user_name": uname,
                    "count": valid_count
                })

        leaderboard.sort(key=lambda x: x['count'], reverse=True)
        return {"status": "success", "data": leaderboard}

    def get_user_records_page(self, uid, page, difficulty="", page_size=10):
        try:
            page = int(page)
            page_size = int(page_size)
        except (ValueError, TypeError):
            return {"status": "error", "message": "参数错误"}

        users_data = self._load_json('user_records.json')
        problem_map = self._load_json('problem_list.json')

        target_user = next((u for u in users_data if str(u.get('user_id')) == str(uid)), None)
        if not target_user:
            return {"status": "error", "message": "用户未找到"}

        all_records = target_user.get('records', [])
        if difficulty:
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

    # ---------- 配置管理（使用用户名作为键） ----------
    def get_monitor_config(self):
        if not self.current_username:
            return {"status": "error", "message": "User not found"}

        monitor_list = []
        try:
            user_ids_data = self._load_json('user_ids.json')
            monitor_list = user_ids_data.get(self.current_username, [])
        except:
            pass

        users_records = self._load_json('user_records.json')
        id_name_map = {str(u['user_id']): u['user_name'] for u in users_records}
        enhanced_list = []
        for m_uid in monitor_list:
            name = id_name_map.get(str(m_uid), "未知用户")
            enhanced_list.append({"id": str(m_uid), "name": name})

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

        # 使用用户名作为键
        data[self.current_username] = new_list
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
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

    def close_app(self):
        self._window.destroy()


if __name__ == '__main__':
    api = Api()
    window = webview.create_window(
        'Luogu Monitor Pro', 'web/index.html',
        width=950, height=800,
        resizable=False, js_api=api, frameless=True, easy_drag=True
    )
    api.set_window(window)
    webview.start(debug=False)
