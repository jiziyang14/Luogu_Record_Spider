import asyncio
import json
import os
import re
from playwright.async_api import async_playwright

PROBLEM_ROW_SELECTORS = [
    "div.list-wrap > div.row",
    "tr.problem-list-row",
    "div.problem-list-item",
    "div.problem-card",
    "div.row",
]

PROBLEM_ID_SELECTORS = [
    "a[href*='/problem/']",
    "td:nth-child(1)",
    "div:nth-child(1)",
]

PROBLEM_NAME_SELECTORS = [
    "a[href*='/problem/']",
    "td:nth-child(2)",
    "div:nth-child(2)",
    "span.problem-name",
]

DIFFICULTY_SELECTORS = [
    "span.difficulty",
    "td.difficulty",
    "div.difficulty",
    "td:nth-child(3)",
    "span.tag",
]

SAVE_DEBUG_HTML = True
DATA_FILE = "problem_list.json"

async def create_browser_context(headless=True):
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=headless)
    context = await browser.new_context()
    return p, browser, context

async def extract_problem_id(row):
    pid_pattern = r'\b(AT_[a-zA-Z0-9_]+|CF\d+[A-Z]?|UVA\d+|S\d+|U\d+|A\d+|T\d+|P\d+|B\d+|SP\d+)'
    for sel in PROBLEM_ID_SELECTORS:
        elem = row.locator(sel).first
        if await elem.count() > 0:
            text = await elem.text_content()
            if text:
                match = re.search(pid_pattern, text)
                if match:
                    return match.group(1)
    full = await row.text_content()
    if full:
        match = re.search(pid_pattern, full)
        if match:
            return match.group(1)
    return None

async def extract_problem_name(row):
    pid_pattern = r'\b(AT_[a-zA-Z0-9_]+|CF\d+[A-Z]?|UVA\d+|S\d+|U\d+|A\d+|T\d+|P\d+|B\d+|SP\d+)'
    for sel in PROBLEM_NAME_SELECTORS:
        elem = row.locator(sel).first
        if await elem.count() > 0:
            text = await elem.text_content()
            if text:
                text = text.strip()
                match = re.search(pid_pattern, text)
                if match:
                    pid = match.group(1)
                    name = re.sub(rf'^{re.escape(pid)}\s*', '', text)
                    if name:
                        return name
                else:
                    return text
    full = await row.text_content()
    if full:
        match = re.search(pid_pattern + r'\s+(.+)', full)
        if match:
            return match.group(2).strip()
    return None

async def extract_difficulty(row):
    for sel in DIFFICULTY_SELECTORS:
        elem = row.locator(sel).first
        if await elem.count() > 0:
            text = await elem.text_content()
            if text:
                text = text.strip()
                if "暂无评定" in text:
                    return "暂无评定"
                if any(kw in text for kw in ['入门', '普及−', '普及', '普及+/提高−', '提高', '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTS']):
                    return text
                text_normalized = text.replace('-', '−')
                if any(kw in text_normalized for kw in ['普及−', '普及+/提高−', '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTS']):
                    return text_normalized
                for kw in ['入门', '普及', '提高', '省选', 'NOI']:
                    if kw in text:
                        return text
    full = await row.text_content()
    if full:
        if "暂无评定" in full:
            return "暂无评定"
        for kw in ['入门', '普及−', '普及', '普及+/提高−', '提高', '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTS']:
            if kw in full:
                return kw
        full_normalized = full.replace('-', '−')
        for kw in ['普及−', '普及+/提高−', '提高+/省选−', '省选/NOI−', 'NOI/NOI+/CTS']:
            if kw in full_normalized:
                return kw
    return "未知"

async def visit_problem_list(context, spider_page):
    page = await context.new_page()
    url = f"https://www.luogu.com.cn/problem/list?type=luogu&page={spider_page}"
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        print(f"第 {spider_page} 页加载失败: {e}")
        await page.close()
        return {}
    found_row_selector = None
    for selector in PROBLEM_ROW_SELECTORS:
        try:
            await page.wait_for_selector(selector, timeout=5000)
            found_row_selector = selector
            print(f"第 {spider_page} 页 使用行选择器 '{selector}' 成功")
            break
        except:
            continue
    if not found_row_selector:
        print(f"第 {spider_page} 页 无法找到任何题目行")
        if SAVE_DEBUG_HTML:
            html = await page.content()
            with open(f"debug_page_{spider_page}.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"已保存 debug_page_{spider_page}.html")
        await page.close()
        return {}
    rows = page.locator(found_row_selector)
    row_count = await rows.count()
    if row_count == 0:
        print(f"第 {spider_page} 页无题目")
        await page.close()
        return {}
    print(f"第 {spider_page} 页 解析到 {row_count} 条题目")
    problem_dict = {}
    for i in range(row_count):
        row = rows.nth(i)
        pid = await extract_problem_id(row)
        name = await extract_problem_name(row)
        difficulty = await extract_difficulty(row)
        if not name and pid:
            full = await row.text_content()
            if full:
                match = re.search(rf'{re.escape(pid)}\s+(.+)', full)
                if match:
                    name = match.group(1).strip()
        if not name:
            name = "未知题目"
        if pid:
            problem_dict[pid] = difficulty
            print(f"  -> 题号: {pid}, 名称: {name}, 难度: {difficulty}")
        else:
            if name and name != "未知题目":
                print(f"  -> 未提取到题号，名称: {name}, 难度: {difficulty} (跳过存储)")
            else:
                print(f"  第 {i+1} 行无法提取任何有效信息，跳过")
    await page.close()
    return problem_dict

async def fetch_total_pages(context):
    page = await context.new_page()
    try:
        print("正在进入题库并检索总页数...")
        await page.goto("https://www.luogu.com.cn/problem/list?type=luogu&page=1", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_function("document.body.innerText.includes('共')", timeout=8000)
        body_text = await page.evaluate("() => document.body.innerText")
        match = re.search(r'共\s*(\d+)\s*页', body_text)
        if match:
            total_pages = int(match.group(1))
            print(f"✅ 全文本搜索成功，题库总页数为: {total_pages}")
            return total_pages
        else:
            print("⚠️ 页面文字中未找到“共 X 页”的文本格式。")
    except Exception as e:
        print(f"❌ 自动获取总页数异常: {e}")
    finally:
        await page.close()
    return None

async def save_data_and_progress(data_dict, last_page):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_page": last_page, "data": data_dict}, f, ensure_ascii=False, indent=2)
    print(f"   [已保存] 题目数: {len(data_dict)}, 最新页码: {last_page}")

async def get_problem():
    p, browser, context = await create_browser_context(headless=False)
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = json.load(f)
            if "data" in content:
                all_problem_dict = content["data"]
                last_page = content.get("last_page", 0)
            else:
                all_problem_dict = content
                last_page = 0
        print(f"加载题目数据，共 {len(all_problem_dict)} 道题目，已爬取到第 {last_page} 页")
    else:
        all_problem_dict = {}
        last_page = 0
        print("未找到题目数据，从空开始")
    total_pages = await fetch_total_pages(context)
    if total_pages is None:
        print("\n❌ 自动获取总页数失败。为了程序能精准结束，请手动干预。")
        while True:
            try:
                user_input = input("👉 请根据网页底部提示，手动输入题库的总页数 (输入数字): ")
                total_pages = int(user_input)
                if total_pages > 0:
                    print(f"✅ 已使用手动输入的总页数: {total_pages}")
                    break
                else:
                    print("❌ 页数必须大于 0")
            except ValueError:
                print("❌ 输入无效，请输入纯数字。")
    if last_page >= total_pages:
        print(f"✅ 已爬取到最大页，无需继续 (已有记录: {last_page}, 总页数: {total_pages})")
        await context.close()
        await browser.close()
        await p.stop()
        return
    start_page = last_page + 1
    batch_size = 10
    for batch_start in range(start_page, total_pages + 1, batch_size):
        end_page = min(batch_start + batch_size - 1, total_pages)
        print(f"\n正在爬取第 {batch_start}~{end_page} 页 (总页数 {total_pages})")
        tasks = []
        for page_num in range(batch_start, end_page + 1):
            tasks.append(asyncio.create_task(visit_problem_list(context, page_num)))
        batch_results = await asyncio.gather(*tasks)
        for data in batch_results:
            if data:
                all_problem_dict.update(data)
        last_page = end_page
        await save_data_and_progress(all_problem_dict, last_page)
        print(f"当前累计 {len(all_problem_dict)} 道题目")
        await asyncio.sleep(1)
    print(f"\n🎉 爬取结束，共 {len(all_problem_dict)} 道题目")
    await save_data_and_progress(all_problem_dict, last_page)
    await context.close()
    await browser.close()
    await p.stop()

if __name__ == "__main__":
    asyncio.run(get_problem())