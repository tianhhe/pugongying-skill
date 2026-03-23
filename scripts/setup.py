"""
KOL Scout 环境检查和自动安装脚本

用法：
  python3 setup.py check    # 检查环境
  python3 setup.py install  # 自动安装缺失依赖
"""
from __future__ import annotations

import subprocess
import sys
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

REQUIRED_PACKAGES = [
    ("playwright", "playwright"),
]


def check_python():
    v = sys.version_info
    ok = v.major == 3 and v.minor >= 9
    status = "✓" if ok else "✗"
    print(f"  {status} Python {v.major}.{v.minor}.{v.micro} {'(需要3.9+)' if not ok else ''}")
    return ok


def check_package(import_name: str, pip_name: str) -> bool:
    try:
        __import__(import_name)
        print(f"  ✓ {pip_name}")
        return True
    except ImportError:
        print(f"  [缺失] {pip_name}")
        return False


def check_playwright_browser() -> bool:
    try:
        result = subprocess.run(
            ["python3", "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True
        )
        # 如果chromium已装，dry-run输出会包含路径
        installed = "chromium" in (result.stdout + result.stderr).lower()
        # 更可靠：直接检查是否能import sync_api
        from playwright.sync_api import sync_playwright
        print("  ✓ Playwright Chromium 驱动")
        return True
    except Exception:
        print("  [缺失] Playwright Chromium 驱动（需要运行 playwright install chromium）")
        return False


def check_chrome_running() -> bool:
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 9222), timeout=2)
        s.close()
        print("  ✓ Chrome CDP 端口9222（已运行）")
        return True
    except Exception:
        print("  [未运行] Chrome 未以 CDP 模式启动（端口9222未监听）")
        return False


def check_dirs():
    for d in ["tmp", "tmp/screenshots", "output"]:
        path = os.path.join(SKILL_DIR, d)
        os.makedirs(path, exist_ok=True)
    print("  ✓ 工作目录已创建")
    return True


def run_check() -> bool:
    print("\nKOL Scout 环境检查")
    print("=" * 40)

    all_ok = True

    print("\n[Python]")
    all_ok &= check_python()

    print("\n[依赖包]")
    for imp, pip in REQUIRED_PACKAGES:
        all_ok &= check_package(imp, pip)

    print("\n[浏览器驱动]")
    all_ok &= check_playwright_browser()

    print("\n[Chrome 状态]")
    chrome_ok = check_chrome_running()
    # Chrome 未运行不算失败，只是提醒

    print("\n[工作目录]")
    check_dirs()

    print("\n" + "=" * 40)
    if all_ok:
        print("✓ 环境就绪，可以运行 kol-scout")
        if not chrome_ok:
            print("\n提醒：运行前请先启动 Chrome 并登录蒲公英和小红书")
    else:
        print("✗ 有依赖未满足，请运行：python3 setup.py install")

    return all_ok


def run_install():
    print("\nKOL Scout 自动安装")
    print("=" * 40)

    # 1. 安装 Python 包
    print("\n[安装依赖包]")
    for imp, pip in REQUIRED_PACKAGES:
        try:
            __import__(imp)
            print(f"  ✓ {pip} 已安装，跳过")
        except ImportError:
            print(f"  安装 {pip}...")
            subprocess.run([sys.executable, "-m", "pip", "install", pip], check=True)
            print(f"  ✓ {pip} 安装完成")

    # 2. 安装 Playwright Chromium 驱动
    print("\n[安装 Playwright Chromium 驱动]")
    try:
        from playwright.sync_api import sync_playwright
        print("  ✓ Playwright 已安装")
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)

    print("  安装 Chromium 驱动（约100MB，首次安装需要几分钟）...")
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    print("  ✓ Chromium 驱动安装完成")

    # 3. 创建工作目录
    print("\n[创建工作目录]")
    check_dirs()

    print("\n" + "=" * 40)
    print("✓ 安装完成！")
    print("\n下一步：")
    print("  1. 启动 Chrome（需要开启 CDP 调试端口9222）")
    print("  2. 在 Chrome 里登录蒲公英：pgy.xiaohongshu.com")
    print("  3. 在 Chrome 里登录小红书：xiaohongshu.com")
    print("  4. 运行 /kol-scout 开始筛选")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    if cmd == "install":
        run_install()
    else:
        run_check()
