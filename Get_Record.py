import asyncio
import json
import time
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, expect

async def visit_user_record_list(context, user_id, existing_records_path="user_records.json", max_pages=None):
    page = await context.new_page()
    user_record = []
    user_name = ""
    existing_records = []
    try:
        with open(existing_records_path, "r", encoding="utf-8") as file:
            existing_data = json.load(file)
            for user_data in existing_data:
                if user_data.get("user_id") == user_id:
                    existing_records = user_data.get("records", [])
                    break
    except (FileNotFoundError, json.JSONDecodeError):
        existing_records = []
    existing_record_set = set()
    for record in existing_records:
        record_key = f"{record.get('problem_number', '')}_{record.get('post_date', '')}"
        existing_record_set.add(record_key)
    print(f"开始爬取用户 {user_id}")
    page_num = 1
    MAX_SAFE_PAGES = 500
    while True:
        if max_pages and page_num > max_pages:
            break
        if page_num > MAX_SAFE_PAGES:
            print(f"用户 {user_id} 已达到安全页数上限 {MAX_SAFE_PAGES}，停止爬取")
            break
        url = f"https://www.luogu.com.cn/record/list?user={user_id}&status=12&page={page_num}"
        retries = 3
        for attempt in range(retries):
            try:
                await page.goto(url, timeout=30000)
                break
            except Exception as e:
                print(f"访问 {url} 失败 (尝试 {attempt+1}/{retries}): {e}")
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(5)
        await asyncio.sleep(1.5)
        first_record = page.locator('//*[@id="app"]/div[2]/main/div/div/div/div[1]/div/div[1]')
        try:
            await expect(first_record).to_be_visible(timeout=3000)
        except:
            break
        try:
            no_record_text = await page.locator('//*[@id="app"]/div[2]/main/div/div/div/div[2]').text_content()
            if "暂时没有符合该筛选条件的提交记录" in no_record_text:
                break
        except:
            pass
        page_new_records = 0
        for i in range(1, 21):
            try:
                record_locator = page.locator(f'//*[@id="app"]/div[2]/main/div/div/div/div[1]/div/div[{i}]')
                count = await record_locator.count()
                if count == 0:
                    break
                text = await record_locator.text_content()
                format_text = text.split("\n")
                if len(format_text) < 10:
                    continue
                if page_num == 1 and i == 1:
                    user_name = format_text[1][2:] if len(format_text[1]) > 2 else "未知用户"
                post_date_str = format_text[3][12:] if len(format_text[3]) > 12 else ""
                if post_date_str.count("-") == 1:
                    post_date_str = str(datetime.now().year) + "-" + post_date_str
                else:
                    post_date_str = post_date_str + ":00"
                problem_number = format_text[8][4:] if len(format_text[8]) > 4 else ""
                problem_name = format_text[9][4:] if len(format_text[9]) > 4 else ""
                record_key = f"{problem_number}_{post_date_str}"
                if record_key not in existing_record_set:
                    user_record.append({
                        "post_date": post_date_str,
                        "problem_number": problem_number,
                        "problem_name": problem_name
                    })
                    existing_record_set.add(record_key)
                    page_new_records += 1
                    await asyncio.sleep(0.05)
            except Exception as e:
                print(f"用户 {user_id} 第 {page_num} 页第 {i} 条记录解析失败：{e}")
                continue
        print(f"用户 {user_id} 第 {page_num} 页新增 {page_new_records} 条记录")
        if page_new_records == 0:
            print(f"用户 {user_id} 第 {page_num} 页新增0条记录，停止爬取本周期")
            break
        page_num += 1
        await asyncio.sleep(0.8)
    await page.close()
    return {"user_id": user_id, "user_name": user_name, "records": user_record}

async def create_browser_context(login_user_id, cookie_path="cookies.json", headless=True):
    with open(cookie_path, "r", encoding="utf-8") as file:
        cookies = json.load(file)
    cookies_list = None
    for i in range(len(cookies)):
        if cookies[i].get("user_id") == login_user_id:
            cookies_list = cookies[i].get("cookies")
            break
    if not cookies_list:
        raise Exception(f"未找到用户 {login_user_id} 的cookies")
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    context = await browser.new_context()
    await context.add_cookies(cookies_list)
    return p, browser, context

async def run_spider(login_user_id, user_ids, cookie_path="cookies.json", existing_records_path="user_records.json", max_pages_per_user=None):
    if not user_ids:
        print("监控列表为空，跳过爬取")
        return []
    p, browser, context = None, None, None
    try:
        p, browser, context = await create_browser_context(login_user_id, cookie_path, headless=True)
        all_user_record_list = []
        batch_size = 10
        for i in range(0, len(user_ids), batch_size):
            batch_user_ids = user_ids[i:i+batch_size]
            print(f"正在爬取第 {i//batch_size + 1} 批用户，共 {len(batch_user_ids)} 个用户")
            tasks = []
            for user_id in batch_user_ids:
                task = asyncio.create_task(
                    visit_user_record_list(context, user_id, existing_records_path, max_pages_per_user)
                )
                tasks.append(task)
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in batch_results:
                if isinstance(result, Exception):
                    print(f"任务失败：{result}")
                else:
                    all_user_record_list.append(result)
            print(f"第 {i//batch_size + 1} 批用户爬取完成")
            if i + batch_size < len(user_ids):
                await asyncio.sleep(2)
        return all_user_record_list
    finally:
        if context:
            await context.close()
        if browser:
            await browser.close()
        if p:
            await p.stop()

def merge_records(existing_records, new_records):
    if not existing_records:
        return new_records
    user_records_map = {}
    for record in existing_records:
        user_id = record["user_id"]
        user_records_map[user_id] = {
            "user_id": user_id,
            "user_name": record["user_name"],
            "records": record["records"]
        }
    for new_record in new_records:
        user_id = new_record["user_id"]
        if user_id in user_records_map:
            existing_record_set = set()
            existing_records_list = user_records_map[user_id]["records"]
            for record in existing_records_list:
                record_key = f"{record.get('problem_number', '')}_{record.get('post_date', '')}"
                existing_record_set.add(record_key)
            for record in new_record["records"]:
                record_key = f"{record.get('problem_number', '')}_{record.get('post_date', '')}"
                if record_key not in existing_record_set:
                    existing_records_list.append(record)
                    existing_record_set.add(record_key)
            if new_record["user_name"] and new_record["user_name"] != "未知用户":
                user_records_map[user_id]["user_name"] = new_record["user_name"]
        else:
            user_records_map[user_id] = new_record
    merged_records = list(user_records_map.values())
    for record in merged_records:
        if record["records"]:
            try:
                record["records"].sort(
                    key=lambda x: datetime.strptime(x["post_date"], "%Y-%m-%d %H:%M:%S") if x["post_date"] else datetime.min,
                    reverse=True
                )
            except:
                pass
    return merged_records

async def schedule_monitoring(login_user_name, interval_minutes=5, user_ids_file="user_ids.json", cookie_path="cookies.json", pause_check=None):
    with open(cookie_path, "r", encoding="utf-8") as file:
        cookies = json.load(file)
    login_user_id = "Unknown_ID"
    for i in cookies:
        if i.get("user_name") == login_user_name:
            login_user_id = i.get("user_id")
            break
    interval_seconds = int(interval_minutes * 60)
    existing_records = []
    try:
        with open("user_records.json", "r", encoding="utf-8") as file:
            existing_records = json.load(file)
        print(f"已加载 {len(existing_records)} 条已有用户记录")
    except (FileNotFoundError, json.JSONDecodeError):
        print("未找到已有记录文件，将创建新文件")
        existing_records = []
    was_paused = False
    while True:
        is_paused = pause_check() if pause_check else False
        if is_paused:
            if not was_paused:
                print("[监控] 已暂停，等待恢复...")
            was_paused = True
            await asyncio.sleep(5)
            continue
        else:
            if was_paused:
                print("[监控] 已恢复，开始执行监控任务")
            was_paused = False
        try:
            start_time = datetime.now()
            print(f"\n{'='*60}")
            print(f"开始执行定时监控任务，时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")
            # 关键修正：指定 encoding="utf-8"
            with open(user_ids_file, "r", encoding="utf-8") as file:
                user_ids_list = json.load(file)
            # 兼容新旧格式
            raw_list = user_ids_list.get(login_user_name, [])
            if isinstance(raw_list, list):
                if len(raw_list) > 0 and isinstance(raw_list[0], dict):
                    user_ids = [item["id"] for item in raw_list]
                else:
                    user_ids = [str(x) for x in raw_list]
            else:
                user_ids = []
            print(f"本次监控用户数量：{len(user_ids)}")

            if user_ids:
                new_user_record_list = await run_spider(
                    login_user_id, user_ids, cookie_path, "user_records.json", max_pages_per_user=None
                )
                merged_records = merge_records(existing_records, new_user_record_list)
                with open("user_records.json", "w", encoding="utf-8") as file:
                    json.dump(merged_records, file, ensure_ascii=False, indent=2)
                existing_records = merged_records
                print(f"本次新爬取记录数：{sum(len(u['records']) for u in new_user_record_list)}")
            else:
                print("监控列表为空，跳过爬取")

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            print(f"本次监控任务完成，耗时：{execution_time:.2f}秒")
            next_time = end_time.timestamp() + interval_seconds
            next_time_str = datetime.fromtimestamp(next_time).strftime("%Y-%m-%d %H:%M:%S")
            print(f"下一次监控将在 {interval_minutes} 分钟后执行，预计时间：{next_time_str}")
            await asyncio.sleep(interval_seconds)
        except Exception as e:
            print(f"监控任务执行出错：{e}")
            import traceback
            traceback.print_exc()
            print(f"将在1分钟后重试...")
            await asyncio.sleep(60)

if __name__ == "__main__":
    interval_minutes = 5
    try:
        asyncio.run(schedule_monitoring("shuaiqbr", interval_minutes))
    except KeyboardInterrupt:
        print("\n监控已手动停止")