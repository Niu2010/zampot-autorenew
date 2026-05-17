import os
import signal
import asyncio
import logging
import random
import requests
from datetime import datetime
from time import sleep
import argparse
from urllib.parse import urlparse, parse_qs


def signal_handler(sig, frame):
    print("\n捕捉到 Ctrl+C，正在退出...")
    exit(1)


signal.signal(signal.SIGINT, signal_handler)


def get_id_from_url(url):
    parsed_url = urlparse(url)
    query_params = parse_qs(parsed_url.query)
    return query_params.get('id', [None])[0]


# 解析参数
parser = argparse.ArgumentParser(description="-k 在脚本运行结束后不结束浏览器")
parser.add_argument('-k', '--keep', action='store_true', help='启用保留模式')
parser.add_argument('-d', '--debug', action='store_true', help='启用调试模式')
parser.add_argument('-r', '--retry', type=int, default=0, help='重试次数（整数）')
iargs = parser.parse_args()

# 配置标准 logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
std_logger = logging.getLogger(__name__)

# 登录信息
username = os.getenv("USERNAME")
password = os.getenv("PASSWORD")

# 通知
info = ""
# tg通知
tgbot_token = os.getenv("TG_TOKEN", "")
user_id = os.getenv("TG_USERID", "")
# chrome的代理
chrome_proxy = os.getenv("CHROME_PROXY")
# 用来判断登录是否成功
login_deny = False

# 全局常量
signurl = "https://auth.zampto.net/sign-in"
signurl_end = "auth.zampto.net/sign-in"
homeurl = "https://dash.zampto.net/homepage"
homeurlend = "/homepage"
overviewurl = "https://dash.zampto.net/overview"
overviewurl_end = "/overview"

# 全局浏览器对象
browser = None
page = None


def error_exit(msg):
    global std_logger, info
    std_logger.debug(f"[ERROR] {msg}")
    info += f"[ERROR] {msg}\n"
    exit(1)


if not username or not password:
    std_logger.warning("💡 请设置环境变量 USERNAME 和 PASSWORD")
    error_exit("❌ 缺少必要的环境变量 USERNAME 或 PASSWORD。")

if not tgbot_token:
    std_logger.warning("⚠️ 环境变量 TG_TOKEN 未设置，Telegram 通知功能将无法使用。")

if not user_id:
    std_logger.warning("⚠️ 环境变量 TG_USERID 未设置，Telegram 通知功能将无法使用。")


def check_google():
    try:
        response = requests.get("https://www.google.com", timeout=5)
        if response.status_code == 200:
            return True
        else:
            print(f"⚠️ 无法访问 Google，tg通知将不起作用，状态码：{response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ ⚠️ 无法访问 Google，tg通知将不起作用：{e}")
        return False


def tg_notifacation(meg):
    global std_logger
    url = f"https://api.telegram.org/bot{tgbot_token}/sendMessage"
    payload = {
        "chat_id": user_id,
        "text": meg
    }
    response = requests.post(url, data=payload)
    if response.status_code != 200:
        std_logger.error("❌ HTTP 请求失败")
        return False
    result = response.json()
    if result.get("ok"):
        std_logger.info("✅ Telegram 发送成功")
        return True
    else:
        std_logger.error("❌ Telegram 返回错误")
        return False


def exit_process(num=0):
    global info, tgbot_token, browser
    if info and info.strip():
        info = f"ℹ️ Zampto服务器续期通知\n用户：{username}\n{info}"
        if check_google() and tgbot_token and user_id:
            tg_notifacation(info)
    if browser:
        try:
            browser.close()
        except Exception:
            pass
    exit(num)


def capture_screenshot(file_name=None, save_dir='screenshots'):
    global page
    os.makedirs(save_dir, exist_ok=True)
    if not file_name:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f'screenshot_{timestamp}.png'
    full_path = os.path.join(save_dir, file_name)
    try:
        page.screenshot(path=full_path, full_page=True)
        print(f"📸 截图已保存：{full_path}")
    except Exception as e:
        print(f"⚠️ 截图失败：{e}")


async def wait_for(a, b=None):
    if b is None:
        b = a
    wait_time = random.uniform(a, b)
    std_logger.debug(f"即将等待 {wait_time:.2f} 秒（范围：{a} 到 {b}）...")
    await asyncio.sleep(wait_time)
    std_logger.debug(f"等待结束：{wait_time:.2f} 秒")


def setup():
    global browser, page
    from cloakbrowser import launch

    launch_args = {
        "headless": True,
        "humanize": True,
    }

    if chrome_proxy:
        launch_args["proxy"] = {
            "server": chrome_proxy
        }
        std_logger.info(f"✅ 代理已配置")

    browser = launch(**launch_args)
    page = browser.new_page()
    std_logger.info("✅ CloakBrowser 启动成功")


async def open_web():
    global page
    std_logger.info("打开登录页面")
    page.goto(signurl)
    await wait_for(10, 15)


async def login():
    global page, info, login_deny
    std_logger.info("开始登录")

    try:
        # 等待用户名输入框
        page.wait_for_selector('[autocomplete="username email"]', timeout=30000)
        u = page.locator('[autocomplete="username email"]')
        u.fill("")
        await asyncio.sleep(1)
        u.type(username, delay=random.randint(50, 150))

        # 点击下一步
        page.locator('button[type="submit"][name="submit"]').click()
        await asyncio.sleep(2)

        # 等待密码框
        page.wait_for_selector('[type="password"]', timeout=30000)
        p = page.locator('[type="password"]')
        p.type(password, delay=random.randint(50, 150))

        # 点击登录
        await asyncio.sleep(1)
        page.locator('button[type="submit"][name="submit"]').click()

        await wait_for(10, 15)

        if signurl_end in page.url:
            msg = f"⚠️ {username}登录失败，请检查认证信息是否正确。"
            login_deny = True
            error_exit(msg)
        else:
            std_logger.info("✅ 登录成功")

        # 跳过可选步骤
        try:
            skip = page.locator('div[role="button"]:has-text("Skip")')
            if skip.is_visible(timeout=3000):
                skip.click()
        except Exception:
            pass

    except Exception as e:
        error_exit(f"登录步骤失败: {e}")


async def open_overview():
    global page
    std_logger.info("打开 Overview 页面")
    if page.url.startswith(homeurl):
        try:
            overview = page.locator('a:has(span:text("Servers Overview"))')
            if overview.is_visible(timeout=5000):
                std_logger.info("找到 overview 入口，点击")
                overview.click()
        except Exception:
            std_logger.error("没有找到 overview 入口，回退到直接访问")
            page.goto(overviewurl)
    else:
        page.goto(overviewurl)

    await wait_for(7, 10)

    # 处理 cookie 弹窗
    try:
        deny = page.locator("button.fc-button.fc-cta-do-not-consent")
        if deny.is_visible(timeout=5000):
            deny.click()
            print('发现 cookie 协议，已跳过')
    except Exception:
        pass


async def open_server_tab():
    global page, info
    std_logger.info("开始续期服务器")

    # 获取所有服务器链接
    links = page.locator("a[href*='server?id']")
    count = links.count()

    if count == 0:
        capture_screenshot("serverlist_overview.png")
        error_exit("⚠️ server_list 为空，跳过服务器续期流程")

    server_list = []
    for i in range(count):
        href = links.nth(i).get_attribute("href")
        if href:
            server_list.append(href)

    std_logger.info(f"找到 {len(server_list)} 台服务器")

    for s in server_list:
        page.goto(s)
        await wait_for(3, 5)

        # 点击 renew 按钮
        try:
            renew_btn = page.locator("a[onclick*='handleServerRenewal']")
            if renew_btn.is_visible(timeout=15000):
                std_logger.debug("找到 renew 按钮，点击")
                renew_btn.click()
                await wait_for(3, 5)
            else:
                std_logger.debug("没找到 renew 按钮，无事发生")
        except Exception:
            std_logger.debug("没找到 renew 按钮，无事发生")

        # 检查续期结果
        try:
            name_span = page.locator("span.server-name")
            name_span.wait_for(timeout=15000)
            server_name = name_span.inner_html()
            if server_name:
                info += f'✅ 服务器 [{server_name}] 续期成功\n'
                std_logger.info(f'✅ 服务器续期成功')
                sleep(5)
                # 报告剩余时间
                try:
                    left_time = page.locator('#nextRenewalTime')
                    if left_time.is_visible(timeout=10000):
                        info += f'🕒 [服务器: {server_name}] 存活期限：{left_time.inner_html()}\n'
                        std_logger.info(f'🕒 存活期限已记录')
                except Exception:
                    pass
            else:
                info += f'❌ 服务器续期失败\n'
                error_exit('❌ 服务器续期失败')
        except Exception as e:
            info += f'❌ 检查续期结果失败: {e}\n'
            error_exit(f'❌ 检查续期结果失败: {e}')

        ser_id = get_id_from_url(s)
        capture_screenshot(f"{ser_id}.png")


steps = [
    {"match": "/newtab/", "action": open_web, "name": "open_web"},
    {"match": signurl_end, "action": login, "name": "account"},
    {"match": homeurlend, "action": open_overview, "name": "open_overview"},
    {"match": overviewurl_end, "action": open_server_tab, "name": "open_server_tab"},
]


def mask_url_domain_last8(url: str, keep: int = 8) -> str:
    if not url:
        return "N/A"
    parsed = urlparse(url)
    domain = f"{parsed.scheme}://{parsed.netloc}"
    last_part = parsed.path.rsplit("/", 1)[-1]
    short_part = last_part[-keep:] if last_part else ""
    return f"{domain}/{short_part}/"


async def continue_execution():
    global page, std_logger
    realurl = page.url
    url = mask_url_domain_last8(realurl)
    std_logger.debug(f"当前页面 URL: {url}")

    start_index = 0
    current_step_name = "unknown"

    for i, step in enumerate(steps):
        if step["match"] in realurl:
            start_index = i
            current_step_name = step.get("name", f"step_{i}")
            std_logger.info(f"检测到当前步骤: {current_step_name}")
            break
    else:
        std_logger.warning(f"未找到匹配的步骤，URL: {url}")
        error_exit("没有匹配的步骤，退出")

    std_logger.info(f"从步骤 {start_index} 开始执行")

    for i, step in enumerate(steps[start_index:], start=start_index):
        step_name = step.get("name", f"step_{i}")
        std_logger.info(f"执行步骤 {i}: {step_name}")
        action = step["action"]
        try:
            result = action()
            if asyncio.iscoroutine(result):
                await result

            std_logger.debug(f"步骤 {step_name} 执行完成")
            await wait_for(5, 7)

            capture_screenshot(f"{step_name}_{i}.png")

            if i < len(steps) - 1:
                await wait_for(3)

        except SystemExit as e:
            raise
        except Exception as e:
            std_logger.error(f"步骤 {step_name} 执行失败: {e}")
            error_exit(f"步骤 {step_name} 执行失败: {e}")
            return 1

    std_logger.info("所有步骤执行完成")
    return 0


async def main():
    global std_logger, iargs
    exit_code = 0
    setup()
    try:
        exit_code = await continue_execution()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
        print(f"捕获到系统退出，退出码: {exit_code}")
    except Exception as e:
        exit_code = 1
        print(f"执行过程中出现错误: {e}")
    finally:
        return exit_code


if __name__ == "__main__":
    if iargs.retry > 0:
        for attempt in range(1, iargs.retry + 1):
            info += f"开始第 {attempt} 次尝试，共 {iargs.retry} 次机会\n"
            success = asyncio.run(main())
            if success == 0:
                std_logger.debug("执行成功，无需重试")
                exit_process(0)
                break
            else:
                std_logger.debug(f"第 {attempt} 次执行失败")
                if attempt < iargs.retry:
                    std_logger.debug("准备重试...")
                else:
                    std_logger.debug("已达到最大重试次数")
        exit_process(success)
    else:
        success = asyncio.run(main())
        exit_process(success)
