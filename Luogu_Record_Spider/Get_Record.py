import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from playwright.async_api import async_playwright, expect


# ---------- 路径辅助函数 ----------
def _safe_path(filename):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


async def visit_user_record_list(context, user_id, existing_records_path="user_records.json", max_pages=None):
    existing_records_path = _safe_path(existing_records_path)
    page = await context.new_page()
    user_record = []
    user_name = ""
    table_head = ["post_date", "problem_number", "problem_name"]

    existing_records = []
    try:
        if os.path.exists(existing_records_path):
            with open(existing_records_path, "r", encoding="utf-8") as file:
                existing_data = json.load(file)
                for user_data in existing_data:
                    if user_data.get("user_id") == user_id:
                        existing_records = user_data.get("records", [])
                        break
    except (json.JSONDecodeError, OSError) as e:
        print(f"读取已存在记录时出错：{e}")

    existing_record_set = set()
    for record in existing_records:
        record_key = f"{record.get('problem_number', '')}_{record.get('post_date', '')}"
        existing_record_set.add(record_key)

    page_num = 1
    MAX_SAFE_PAGES = 500
    while True:
        if max_pages and page_num > max_pages:
            break
        if page_num > MAX_SAFE_PAGES:
            print(f"用户 {user_id} 已达到安全页数上限 {MAX_SAFE_PAGES}，停止爬取")
            break

        url = f"https://www.luogu.com.cn/record/list?user={user_id}&status=12&page={page_num}"
        await page.goto(url)
        print(f"已访问用户 {user_id} 第 {page_num} 页")
        await page.wait_for_timeout(1000)

        first_record = page.locator('//*[@id="app"]/div[2]/main/div/div/div/div[1]/div/div[1]')
        try:
            await expect(first_record).to_be_visible(timeout=3000)
        except:
            print(f"用户 {user_id} 第 {page_num} 页没有记录，爬取结束")
            break

        try:
            no_record_text = await page.locator('//*[@id="app"]/div[2]/main/div/div/div/div[2]').text_content()
            if "暂时没有符合该筛选条件的提交记录" in no_record_text:
                print(f"用户 {user_id} 没有提交记录")
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
                    await page.wait_for_timeout(0.05)
            except Exception as e:
                print(f"用户 {user_id} 第 {page_num} 页第 {i} 条记录解析失败：{e}")
                continue

        print(f"用户 {user_id} 第 {page_num} 页新增 {page_new_records} 条记录")
        page_num += 1
        await asyncio.sleep(0.5)

    await page.close()
    return {"user_id": user_id, "user_name": user_name, "records": user_record}


async def create_browser_context(login_user_name, cookie_path="cookies.json", headless=True):
    cookie_path = _safe_path(cookie_path)
    with open(cookie_path, "r") as file:
        cookies = json.load(file)

    for i in range(len(cookies)):
        if cookies[i].get("user_name") == login_user_name:  # 按用户名匹配
            cookies_list = cookies[i].get("cookies")
            break

    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    context = await browser.new_context()
    await context.add_cookies(cookies_list)
    return p, browser, context


async def run_spider(login_user_name, user_ids, cookie_path="cookies.json", existing_records_path="user_records.json", max_pages_per_user=None):
    cookie_path = _safe_path(cookie_path)
    existing_records_path = _safe_path(existing_records_path)
    p, browser, context = None, None, None
    try:
        p, browser, context = await create_browser_context(login_user_name, cookie_path, headless=True)
        all_user_record_list = []

        for i in range(0, len(user_ids), 10):
            batch_user_ids = user_ids[i:i+10]
            print(f"正在爬取第 {i//10 + 1} 批用户，共 {len(batch_user_ids)} 个用户")

            tasks = []
            for user_id in batch_user_ids:
                task = asyncio.create_task(
                    visit_user_record_list(
                        context,
                        user_id,
                        existing_records_path,
                        max_pages_per_user
                    )
                )
                tasks.append(task)

            batch_results = await asyncio.gather(*tasks)
            all_user_record_list.extend(batch_results)
            print(f"第 {i//10 + 1} 批用户爬取完成")
            if i + 10 < len(user_ids):
                await asyncio.sleep(1)

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
            existing_set = set()
            for rec in user_records_map[user_id]["records"]:
                existing_set.add(f"{rec.get('problem_number','')}_{rec.get('post_date','')}")
            for rec in new_record["records"]:
                key = f"{rec.get('problem_number','')}_{rec.get('post_date','')}"
                if key not in existing_set:
                    user_records_map[user_id]["records"].append(rec)
                    existing_set.add(key)
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


async def schedule_monitoring(login_user_name, interval_minutes=5, user_ids_file="user_ids.json", cookie_path="cookies.json"):
    user_ids_file = _safe_path(user_ids_file)
    cookie_path = _safe_path(cookie_path)
    records_path = _safe_path("user_records.json")

    with open(cookie_path, "r") as file:
        cookies = json.load(file)

    # 登录用户名已经直接可用
    interval_seconds = int(interval_minutes * 60)

    existing_records = []
    if os.path.exists(records_path):
        try:
            with open(records_path, "r", encoding="utf-8") as file:
                existing_records = json.load(file)
        except (json.JSONDecodeError, OSError) as e:
            print(f"读取 {records_path} 出错：{e}")

    while True:
        try:
            start_time = datetime.now()
            print(f"\n{'='*60}")
            print(f"开始执行定时监控任务，时间：{start_time.strftime('%Y-%m-%d %H:%M:%S')}")

            # 读取监控用户列表，键为用户名
            user_ids = []
            if os.path.exists(user_ids_file):
                try:
                    with open(user_ids_file, "r", encoding="utf-8") as file:
                        user_ids_list = json.load(file)
                    if isinstance(user_ids_list, dict):
                        user_ids = user_ids_list.get(login_user_name, [])
                    else:
                        print(f"警告：{user_ids_file} 格式错误")
                except (json.JSONDecodeError, OSError) as e:
                    print(f"警告：读取 {user_ids_file} 失败：{e}")
            else:
                # 文件不存在则创建空文件
                with open(user_ids_file, "w", encoding="utf-8") as f:
                    json.dump({}, f)

            if not isinstance(user_ids, list):
                user_ids = []

            print(f"本次监控用户数量：{len(user_ids)}")
            if len(user_ids) == 0:
                print("监控列表为空，跳过本次爬取")
                await asyncio.sleep(interval_seconds)
                continue

            new_user_record_list = await run_spider(
                login_user_name,
                user_ids,
                cookie_path,
                records_path,
                max_pages_per_user=None
            )

            merged_records = merge_records(existing_records, new_user_record_list)
            with open(records_path, "w", encoding="utf-8") as file:
                json.dump(merged_records, file, ensure_ascii=False, indent=2)

            existing_records = merged_records

            end_time = datetime.now()
            execution_time = (end_time - start_time).total_seconds()
            print(f"本次监控任务完成，耗时：{execution_time:.2f}秒")
            print(f"主记录文件已更新：{records_path}")
            print(f"总用户记录数：{len(merged_records)}")

            next_time = end_time.timestamp() + interval_seconds
            next_time_str = datetime.fromtimestamp(next_time).strftime("%Y-%m-%d %H:%M:%S")
            print(f"下一次监控将在 {interval_minutes} 分钟后执行，预计时间：{next_time_str}")
            print(f"{'='*60}\n")

            await asyncio.sleep(interval_seconds)

        except Exception as e:
            print(f"监控任务执行出错：{e}")
            import traceback
            traceback.print_exc()
            print("将在1分钟后重试...")
            await asyncio.sleep(60)


if __name__ == "__main__":
    interval_minutes = 5
    try:
        asyncio.run(schedule_monitoring("shuaiqbr", interval_minutes))
    except KeyboardInterrupt:
        print("\n监控已手动停止")