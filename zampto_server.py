import os
import signal
import asyncio
import logging
import random
import requests
from datetime import datetime
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
username = os.getenv("ZAMPTO_USER")  # workflow 中将 secrets.USERNAME 映射为 ZAMPTO_USER，避免与系统变量冲突
password = os.getenv("PASSWORD")

# 通知
info = ""
# tg通知
tgbot_token = os.getenv("TG_TOKEN", "")
user_id = os.getenv("TG_USERID", "")
# chrome代理
chrome_proxy = os.getenv("CHROME_PROXY")

# 服务器 ID 列表，逗号分隔，例如："6119,6120,6121"
# 在 GitHub Actions Secrets 中设置 SERVER_IDS
_server_ids_raw = os.getenv("SERVER_IDS", "")
server_ids = [s.strip() for s in _server_ids_raw.split(",") if s.strip()]

# 全局常量
signurl = "https://auth.zampto.net/sign-in"
signurl_end = "auth.zampto.net/sign-in"
serverbaseurl = "https://dash.zampto.net/server?id="

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
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        print(f"❌ 无法访问 Google：{e}")
        return False


def tg_notifacation(meg):
    url = f"https://api.telegram.org/bot{tgbot_token}/sendMessage"
    payload = {"chat_id": user_id, "text": meg}
    try:
        response = requests.post(url, data=payload)
        if response.status_code == 200 and response.json().get("ok"):
            std_logger.info("✅ Telegram 发送成功")
            return True
    except Exception as e:
        std_logger.error(f"❌ Telegram 发送失败: {e}")
    return False


def exit_process(num=0):
    global info, tgbot_token
    if info and info.strip():
        info = f"ℹ️ Zampto服务器续期通知\n用户：{username}\n{info}"
        if check_google() and tgbot_token and user_id:
            tg_notifacation(info)
    exit(num)


async def capture_screenshot(file_name=None, save_dir='screenshots'):
    global page
    os.makedirs(save_dir, exist_ok=True)
    if not file_name:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        file_name = f'screenshot_{timestamp}.png'
    full_path = os.path.join(save_dir, file_name)
    try:
        await page.screenshot(path=full_path, full_page=True)  # 修复：改为 await
        print(f"📸 截图已保存：{full_path}")
    except Exception as e:
        print(f"⚠️ 截图失败：{e}")


async def wait_for(a, b=None):
    if b is None:
        b = a
    wait_time = random.uniform(a, b)
    std_logger.debug(f"即将等待 {wait_time:.2f} 秒")
    await asyncio.sleep(wait_time)


async def setup():
    global browser, page
    from cloakbrowser import launch_async  # 修复：正确的导入路径

    launch_args = {
        "headless": True,
        "humanize": True,
    }

    if chrome_proxy:
        launch_args["proxy"] = chrome_proxy  # 修复：proxy 直接传字符串，不是 dict
        std_logger.info("✅ 代理已配置")

    browser = await launch_async(**launch_args)
    page = await browser.new_page()
    std_logger.info("✅ CloakBrowser 启动成功")


async def open_web():
    global page
    std_logger.info("打开登录页面")
    await page.goto(signurl)
    await wait_for(10, 15)


async def login():
    global page, info
    std_logger.info("开始登录")
    try:
        await page.wait_for_selector('[autocomplete="username email"]', timeout=30000)
        u = page.locator('[autocomplete="username email"]')
        await u.fill("")
        await asyncio.sleep(1)
        await u.type(username, delay=random.randint(50, 150))

        await page.locator('button[type="submit"][name="submit"]').click()
        await asyncio.sleep(2)

        await page.wait_for_selector('[type="password"]', timeout=30000)
        p = page.locator('[type="password"]')
        await p.type(password, delay=random.randint(50, 150))

        await asyncio.sleep(1)
        await page.locator('button[type="submit"][name="submit"]').click()

        await wait_for(10, 15)

        if signurl_end in page.url:
            error_exit(f"⚠️ {username}登录失败，请检查认证信息是否正确。")
        else:
            std_logger.info("✅ 登录成功")

        try:
            skip = page.locator('div[role="button"]:has-text("Skip")')
            if await skip.is_visible(timeout=3000):
                await skip.click()
        except Exception:
            pass

    except SystemExit:
        raise
    except Exception as e:
        error_exit(f"登录步骤失败: {e}")


async def open_server_tab():
    global page, info
    std_logger.info("开始续期服务器")

    if not server_ids:
        error_exit("⚠️ SERVER_IDS 环境变量未设置，请在 Secrets 中添加服务器 ID，例如：6119 或 6119,6120")

    std_logger.info(f"找到 {len(server_ids)} 台服务器：{server_ids}")

    for sid in server_ids:
        s = f"{serverbaseurl}{sid}"
        await page.goto(s, wait_until="networkidle")
        await wait_for(3, 5)

        try:
            renew_btn = page.locator("a[onclick*='handleServerRenewal']")
            if await renew_btn.is_visible(timeout=15000):
                std_logger.debug("找到 renew 按钮，点击")
                await renew_btn.click()
                await wait_for(3, 5)
            else:
                std_logger.debug("没找到 renew 按钮，无事发生")
        except Exception:
            std_logger.debug("没找到 renew 按钮，无事发生")

        try:
            name_span = page.locator("span.server-name")
            await name_span.wait_for(timeout=15000)
            server_name = await name_span.inner_html()
            if server_name:
                info += f'✅ 服务器 [{server_name}] 续期成功\n'
                std_logger.info('✅ 服务器续期成功')
                await asyncio.sleep(5)
                try:
                    left_time = page.locator('#nextRenewalTime')
                    if await left_time.is_visible(timeout=10000):
                        lt = await left_time.inner_html()
                        info += f'🕒 [服务器: {server_name}] 存活期限：{lt}\n'
                except Exception:
                    pass
            else:
                info += f'❌ 服务器 [{sid}] 续期失败\n'
                error_exit(f'❌ 服务器 [{sid}] 续期失败')
        except SystemExit:
            raise
        except Exception as e:
            info += f'❌ 检查续期结果失败: {e}\n'
            error_exit(f'❌ 检查续期结果失败: {e}')

        await capture_screenshot(f"{sid}.png")


steps = [
    {"match": signurl_end, "action": login, "name": "account"},
    {"match": "dash.zampto.net", "action": open_server_tab, "name": "open_server_tab"},
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
    global page

    await open_web()
    std_logger.debug(f"当前页面 URL: {mask_url_domain_last8(page.url)}")

    # 执行登录
    std_logger.info("执行步骤 1: account")
    await login()
    std_logger.debug("步骤 account 执行完成")
    await wait_for(3, 5)
    await capture_screenshot("account_1.png")

    # 直接续期
    std_logger.info("执行步骤 2: open_server_tab")
    await open_server_tab()
    std_logger.debug("步骤 open_server_tab 执行完成")
    await capture_screenshot("open_server_tab_2.png")

    std_logger.info("所有步骤执行完成")
    return 0


async def main():
    global browser
    exit_code = 0
    await setup()
    try:
        exit_code = await continue_execution()
    except SystemExit as e:
        exit_code = e.code if isinstance(e.code, int) else 1
        print(f"捕获到系统退出，退出码: {exit_code}")
    except Exception as e:
        exit_code = 1
        print(f"执行过程中出现错误: {e}")
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        return exit_code


if __name__ == "__main__":
    if iargs.retry > 0:
        success = 1
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
                    info += f"第 {attempt} 次失败，准备重试...\n"
                else:
                    std_logger.debug("已达到最大重试次数")
        exit_process(success)
    else:
        success = asyncio.run(main())
        exit_process(success)
