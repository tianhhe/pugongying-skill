"""
蒲公英达人初筛脚本

用 Playwright CDP 连接已登录的 Chrome，在蒲公英后台达人广场
截图给 Claude 视觉读取，初筛达人，输出报告。

用法：
  python scripts/scout.py check          # 检查连接，截图当前页面
  python scripts/scout.py screenshot     # 截图当前页面并输出路径
  python scripts/scout.py goto URL       # 导航到指定 URL
  python scripts/scout.py scroll [down|up] [距离]
  python scripts/scout.py click X Y      # 点击坐标
  python scripts/scout.py scan --count 20 --output ~/Desktop/达人初筛报告.md
"""

from __future__ import annotations
import argparse, json, math, os, random, sys, time
from datetime import datetime
from pathlib import Path

# 绕过系统代理（Squid），避免本地 CDP 连接被拦截
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
    os.environ.pop(_k, None)

# ── 路径 ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent.resolve()
SKILL_DIR  = SCRIPT_DIR.parent
SS_DIR     = SKILL_DIR / "tmp" / "screenshots"
SS_DIR.mkdir(parents=True, exist_ok=True)

CDP_PORT = 9222

PUGONGYING_TALENT_URL = "https://pgy.xiaohongshu.com/solar/pre-trade/note/kol"


# ── CDP 连接（Playwright）────────────────────────────────────────────────────

def connect_cdp():
    """连接到已运行的 Chrome（端口9222），返回 (pw, browser, page)。"""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    except Exception as e:
        print(f"[错误] 无法连接 Chrome CDP（端口 {CDP_PORT}）：{e}")
        print()
        print("请先启动 Chrome：")
        print('  "/Applications/Google Chrome 2.app/Contents/MacOS/Google Chrome 2" \\')
        print("    --remote-debugging-port=9222 \\")
        print("    --user-data-dir=/Users/kanyun/browser_profile \\")
        print("    --remote-allow-origins=*")
        sys.exit(1)
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, browser, page


# ── 截图 ──────────────────────────────────────────────────────────────────────

def do_screenshot(page, name: str | None = None) -> str:
    if not name:
        name = f"pgy_{int(time.time())}.png"
    if not name.endswith(".png"):
        name += ".png"
    path = str(SS_DIR / name)
    page.screenshot(path=path)
    print(path)
    return path


# ── 人类模拟鼠标 ──────────────────────────────────────────────────────────────

def _bezier_point(t, p0, p1, p2, p3):
    u = 1 - t
    return u**3*p0 + 3*u**2*t*p1 + 3*u*t**2*p2 + t**3*p3


def human_move(page, to_x: float, to_y: float, from_x: float = 640, from_y: float = 450):
    dx, dy = to_x - from_x, to_y - from_y
    dist = math.sqrt(dx*dx + dy*dy)
    steps = max(8, min(25, int(dist / 20)))
    perp_x = -dy / max(dist, 1)
    perp_y =  dx / max(dist, 1)
    curve = random.uniform(-0.2, 0.2) * dist
    cp1x = from_x + dx*0.25 + perp_x*curve*random.uniform(0.5, 1.5)
    cp1y = from_y + dy*0.25 + perp_y*curve*random.uniform(0.5, 1.5)
    cp2x = from_x + dx*0.75 + perp_x*curve*random.uniform(0.3, 0.8)
    cp2y = from_y + dy*0.75 + perp_y*curve*random.uniform(0.3, 0.8)
    for i in range(steps + 1):
        t = i / steps
        te = t*t*(3 - 2*t)
        x = _bezier_point(te, from_x, cp1x, cp2x, to_x)
        y = _bezier_point(te, from_y, cp1y, cp2y, to_y)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.005, 0.015))


def human_click(page, x: float, y: float):
    human_move(page, x, y)
    time.sleep(random.uniform(0.05, 0.12))
    page.mouse.down()
    time.sleep(random.uniform(0.04, 0.10))
    page.mouse.up()
    time.sleep(random.uniform(0.3, 0.6))


def human_scroll(page, direction: str = "down", distance: int = 400):
    sign = 1 if direction == "down" else -1
    chunks = random.randint(3, 5)
    per = distance // chunks
    for _ in range(chunks):
        page.mouse.wheel(0, (per + random.randint(-10, 10)) * sign)
        time.sleep(random.uniform(0.08, 0.2))
    time.sleep(0.3)


def natural_pause(min_s: float = 0.8, max_s: float = 2.0):
    time.sleep(random.uniform(min_s, max_s))


# ── 子命令 ────────────────────────────────────────────────────────────────────

def cmd_check(args):
    """检查连接，截图当前页面。"""
    pw, browser, page = connect_cdp()
    print(f"[OK] 已连接 Chrome，当前 URL：{page.url}")
    path = do_screenshot(page, "check")
    print(f"[截图] {path}")
    browser.close()
    pw.stop()


def cmd_screenshot(args):
    """截图当前页面。"""
    pw, browser, page = connect_cdp()
    name = args.name if hasattr(args, "name") and args.name else None
    path = do_screenshot(page, name)
    browser.close()
    pw.stop()


def cmd_goto(args):
    """导航到指定 URL。"""
    pw, browser, page = connect_cdp()
    print(f"[导航] {args.url}")
    page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
    natural_pause(2.0, 3.5)
    path = do_screenshot(page, "goto")
    print(f"[截图] {path}")
    browser.close()
    pw.stop()


def cmd_scroll(args):
    """滚动页面并截图。"""
    pw, browser, page = connect_cdp()
    direction = args.direction if hasattr(args, "direction") and args.direction else "down"
    distance  = int(args.distance) if hasattr(args, "distance") and args.distance else 400
    print(f"[滚动] {direction} {distance}px")
    human_scroll(page, direction, distance)
    natural_pause(0.5, 1.2)
    path = do_screenshot(page)
    print(f"[截图] {path}")
    browser.close()
    pw.stop()


def cmd_click(args):
    """点击指定坐标并截图。"""
    pw, browser, page = connect_cdp()
    x, y = float(args.x), float(args.y)
    print(f"[点击] ({x}, {y})")
    human_click(page, x, y)
    natural_pause(1.0, 2.0)
    path = do_screenshot(page)
    print(f"[截图] {path}")
    browser.close()
    pw.stop()


def cmd_profile(args):
    """
    截图当前达人主页：简介顶部 + 滚动三屏作品（约15篇）。
    在 scan 流程中，点进达人主页后调用此命令。
    """
    pw, browser, page = connect_cdp()
    name  = args.name  if hasattr(args, "name")  and args.name  else "talent"
    index = int(args.index) if hasattr(args, "index") and args.index else 0
    print(f"[主页截图] {name} (#{index})")
    shots = screenshot_talent_profile(page, name, index)
    print(f"[完成] 共 {len(shots)} 张截图")
    browser.close()
    pw.stop()


def cmd_back(args):
    """返回上一页并截图，确认回到列表。"""
    pw, browser, page = connect_cdp()
    print("[返回] 上一页")
    page.go_back(wait_until="domcontentloaded", timeout=15000)
    natural_pause(1.5, 2.5)
    path = do_screenshot(page, f"back_{int(time.time())}")
    print(f"[截图] {path}")
    browser.close()
    pw.stop()


def cmd_open_talent_market(args):
    """打开蒲公英达人广场并截图。"""
    pw, browser, page = connect_cdp()
    print(f"[导航] 打开蒲公英达人广场…")
    page.goto(PUGONGYING_TALENT_URL, wait_until="domcontentloaded", timeout=30000)
    natural_pause(2.5, 4.0)
    path = do_screenshot(page, "talent_market")
    print(f"[截图] {path}")
    print("[提示] 请用 Read 工具查看截图，确认页面已正确加载")
    browser.close()
    pw.stop()


def screenshot_talent_profile(page, talent_name: str, index: int) -> list[str]:
    """
    在达人主页截图：
    - 第1张：主页顶部（头像、昵称、简介）
    - 第2张：滚动后，作品列表第一屏（约5-8篇）
    - 第3张：继续滚动，作品列表第二屏
    - 第4张：继续滚动，作品列表第三屏（共约15篇以上）
    """
    safe_name = "".join(c for c in talent_name if c.isalnum() or c in "._-")[:20] or f"talent{index}"
    prefix = f"talent_{index:02d}_{safe_name}"
    shots = []

    # 等页面加载
    natural_pause(2.0, 3.5)

    # 第1张：顶部简介区
    path = do_screenshot(page, f"{prefix}_1_profile")
    shots.append(path)
    print(f"  [截图] 主页简介 → {path}")

    # 滚动到作品区，截三屏（约15篇作品）
    for i in range(2, 5):
        human_scroll(page, "down", random.randint(450, 600))
        natural_pause(1.2, 2.2)
        path = do_screenshot(page, f"{prefix}_{i}_posts")
        shots.append(path)
        print(f"  [截图] 作品第{i-1}屏 → {path}")

    return shots


def cmd_scan(args):
    """
    达人初筛主流程：
    1. 打开蒲公英达人广场列表页，截图
    2. Claude 视觉读取列表，提取每行达人的昵称和主页链接
    3. 逐一点进达人主页，截图简介 + 滚动截图作品（约15篇）
    4. 返回列表，继续下一个
    5. 所有截图完成后，Claude 视觉分析全部截图，写初筛报告
    """
    count  = args.count
    output = args.output or f"~/Desktop/达人初筛报告_{datetime.now().strftime('%Y%m%d_%H%M')}.md"

    pw, browser, page = connect_cdp()
    print(f"[当前页面] {page.url}")

    # 如果不在蒲公英，先导航
    if "pgy.xiaohongshu.com" not in page.url:
        print("[导航] 打开蒲公英达人广场…")
        page.goto(PUGONGYING_TALENT_URL, wait_until="domcontentloaded", timeout=30000)
        natural_pause(2.5, 4.0)

    # ── Step 1: 截图列表页，让 Claude 读取达人入口 ──
    list_shots = []
    screens_needed = max(1, count // 6 + 1)  # 每屏约6个达人
    for i in range(1, screens_needed + 1):
        path = do_screenshot(page, f"list_page_{i}")
        list_shots.append(path)
        print(f"[列表截图{i}] {path}")
        if i < screens_needed:
            human_scroll(page, "down", random.randint(350, 480))
            natural_pause(1.0, 1.8)

    # 滚回顶部，准备逐一点入
    page.keyboard.press("Home")
    natural_pause(1.0, 1.5)

    browser.close()
    pw.stop()

    # ── 输出给 Claude 的操作指引 ──
    print("\n" + "=" * 60)
    print("【Step 1 完成】列表页截图：")
    for p in list_shots:
        print(f"  {p}")
    print()
    print("【下一步指引 - Claude 请执行】")
    print(f"""
1. 用 Read 工具查看上述列表截图
2. 从截图中提取每个达人的：昵称、所在行的大概 Y 坐标
3. 对前 {count} 个达人，依次执行：
   a. python scripts/scout.py click <X> <Y>   # 点击达人行，进入主页
   b. python scripts/scout.py profile <昵称> <序号>  # 截图主页（简介+滚动3屏作品）
   c. python scripts/scout.py back            # 返回列表页
   d. 等 1-2 秒后继续下一个
4. 所有达人看完后，用 Read 工具查看全部截图
5. 综合判断每个达人，写初筛报告到：{output}

【判断标准】
产品：斑马口语（7-9岁儿童英语口语）
A级 优先跟进：简介提到有小学生孩子（6-12岁）+ 历史作品有推过教育类产品
B级 值得考虑：满足其中一条，或受众明显是小学生家长
C级 暂时跳过：孩子太小（婴幼儿）、无孩子信息、或受众明显不是家长

【报告格式】参见 SKILL.md
""")
    print("=" * 60)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="蒲公英达人初筛工具")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("check", help="检查连接并截图当前页面")

    ss_p = sub.add_parser("screenshot", help="截图当前页面")
    ss_p.add_argument("name", nargs="?", default=None, help="截图文件名（可选）")

    goto_p = sub.add_parser("goto", help="导航到 URL")
    goto_p.add_argument("url")

    scroll_p = sub.add_parser("scroll", help="滚动页面")
    scroll_p.add_argument("direction", nargs="?", default="down", choices=["down", "up"])
    scroll_p.add_argument("distance", nargs="?", default=400, type=int)

    click_p = sub.add_parser("click", help="点击坐标")
    click_p.add_argument("x", type=float)
    click_p.add_argument("y", type=float)

    sub.add_parser("open", help="打开蒲公英达人广场")

    profile_p = sub.add_parser("profile", help="截图当前达人主页（简介+滚动3屏作品）")
    profile_p.add_argument("name", nargs="?", default="talent", help="达人昵称（用于命名截图）")
    profile_p.add_argument("index", nargs="?", default=0, help="达人序号（用于命名截图）")

    sub.add_parser("back", help="返回上一页")

    scan_p = sub.add_parser("scan", help="截图列表页，引导 Claude 逐一进入主页初筛")
    scan_p.add_argument("--count", type=int, default=20, help="目标筛选数量（默认20）")
    scan_p.add_argument("--output", type=str, default=None, help="报告输出路径")

    args = parser.parse_args()

    dispatch = {
        "check":      cmd_check,
        "screenshot": cmd_screenshot,
        "goto":       cmd_goto,
        "scroll":     cmd_scroll,
        "click":      cmd_click,
        "open":       cmd_open_talent_market,
        "profile":    cmd_profile,
        "back":       cmd_back,
        "scan":       cmd_scan,
    }

    fn = dispatch.get(args.command)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
