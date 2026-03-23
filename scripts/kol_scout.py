"""
KOL Scout — 蒲公英达人筛选系统主控脚本

用法：
  python kol_scout.py run              # 完整流程（蒲公英初筛 → 主页分析 → 生成报告）
  python kol_scout.py scout            # 只跑蒲公英初筛
  python kol_scout.py analyze          # 只跑小红书主页分析（用已有的candidates.json）
  python kol_scout.py report           # 只生成报告（用已有的profiles.json）

前提：
  - Chrome 已启动并连接 CDP（端口9222）
  - Chrome 已登录蒲公英后台和小红书
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# ── 默认配置 ──────────────────────────────────────────────────────────────────

CONFIG = {
    # 蒲公英筛选条件
    "pgy_filters": {
        "categories": ["母婴亲子", "教育", "育儿", "家庭", "生活方式"],
        "min_fans": 10_000,
        "max_fans": 500_000,
        "min_avg_interact": 200,
    },
    "max_candidates": 50,          # 蒲公英初筛最多抓取达人数

    # 小红书分析
    "notes_per_kol": 20,           # 每个达人分析最近N篇笔记
    "delay_between_kols": (4, 8),  # 达人之间停顿时间（秒）

    # 文件路径
    "candidates_path": "tmp/candidates.json",
    "profiles_path": "tmp/profiles.json",
    "output_dir": "output",
    "screenshot_dir": "tmp/screenshots",
}


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def check_chrome_running(port: int = 9222) -> bool:
    import socket
    try:
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        sock.close()
        return True
    except (ConnectionRefusedError, OSError):
        return False


def ensure_dirs():
    for d in ["tmp", "tmp/screenshots", "output"]:
        os.makedirs(d, exist_ok=True)


def print_banner():
    print("""
╔══════════════════════════════════════════════════════════╗
║           KOL Scout — 蒲公英达人筛选系统               ║
║           产品：请在 config 中配置                     ║
╚══════════════════════════════════════════════════════════╝
""")


# ── 各阶段入口 ────────────────────────────────────────────────────────────────

def cmd_scout(args, config: dict):
    """蒲公英初筛"""
    if not check_chrome_running():
        print("[错误] Chrome未运行或CDP未开启（端口9222）")
        print("请先启动Chrome：python ~/.claude/skills/xiaohongshuskills/scripts/chrome_launcher.py")
        sys.exit(1)

    from pugongying_scout import run_scout, DEFAULT_FILTERS

    filters = {
        **DEFAULT_FILTERS,
        "min_fans": args.min_fans or config["pgy_filters"]["min_fans"],
        "max_fans": args.max_fans or config["pgy_filters"]["max_fans"],
        "min_avg_interact": args.min_interact or config["pgy_filters"]["min_avg_interact"],
    }

    candidates = run_scout(
        filters=filters,
        max_candidates=args.max_count or config["max_candidates"],
        output_path=config["candidates_path"],
        screenshot_dir=config["screenshot_dir"],
    )
    print(f"\n初筛完成：{len(candidates)} 人候选")
    return candidates


def cmd_analyze(args, config: dict):
    """小红书主页分析"""
    if not check_chrome_running():
        print("[错误] Chrome未运行或CDP未开启（端口9222）")
        sys.exit(1)

    candidates_path = args.input or config["candidates_path"]
    if not os.path.exists(candidates_path):
        print(f"[错误] 候选名单不存在: {candidates_path}")
        print("请先运行: python kol_scout.py scout")
        sys.exit(1)

    from xhs_profiler import run_profiler

    profiles = run_profiler(
        candidates_path=candidates_path,
        output_path=config["profiles_path"],
        notes_per_kol=config["notes_per_kol"],
        screenshot_dir=config["screenshot_dir"],
        delay_between=config["delay_between_kols"],
    )
    return profiles


def cmd_report(args, config: dict):
    """生成评级报告"""
    profiles_path = args.input or config["profiles_path"]
    if not os.path.exists(profiles_path):
        print(f"[错误] profiles文件不存在: {profiles_path}")
        print("请先运行: python kol_scout.py analyze")
        sys.exit(1)

    from kol_analyzer import generate_report

    report_path = generate_report(
        profiles_path=profiles_path,
        output_dir=config["output_dir"],
    )
    return report_path


def cmd_run(args, config: dict):
    """完整流程"""
    print_banner()
    print("流程：蒲公英初筛 → 小红书主页分析 → 生成报告\n")

    # Step 1
    print("【第一步】蒲公英达人初筛")
    print("-" * 40)
    cmd_scout(args, config)

    # 确认继续
    candidates_path = config["candidates_path"]
    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)
    valid = [c for c in candidates if c.get("xhs_url")]
    print(f"\n初筛结果：{len(candidates)} 人候选，其中 {len(valid)} 人有小红书链接")

    if not valid:
        print("[警告] 没有找到有小红书链接的达人，检查蒲公英页面后重试")
        sys.exit(0)

    print(f"\n即将分析 {len(valid)} 个达人的小红书主页...")
    input("按 Enter 继续，或 Ctrl+C 退出...")

    # Step 2
    print("\n【第二步】小红书主页分析")
    print("-" * 40)
    cmd_analyze(args, config)

    # Step 3
    print("\n【第三步】生成评级报告")
    print("-" * 40)
    report_path = cmd_report(args, config)

    print(f"\n✓ 全部完成！报告：{report_path}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ensure_dirs()

    parser = argparse.ArgumentParser(
        description="KOL Scout — 蒲公英达人筛选系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python kol_scout.py run                           # 完整流程
  python kol_scout.py scout --min-fans 20000        # 只初筛，粉丝2万起
  python kol_scout.py analyze --input my_list.json  # 分析指定名单
  python kol_scout.py report                        # 生成报告
        """,
    )

    sub = parser.add_subparsers(dest="cmd")

    # run
    p_run = sub.add_parser("run", help="完整流程")
    _add_scout_args(p_run)

    # scout
    p_scout = sub.add_parser("scout", help="蒲公英初筛")
    _add_scout_args(p_scout)

    # analyze
    p_analyze = sub.add_parser("analyze", help="小红书主页分析")
    p_analyze.add_argument("--input", help="候选名单JSON路径（默认: tmp/candidates.json）")

    # report
    p_report = sub.add_parser("report", help="生成评级报告")
    p_report.add_argument("--input", help="profiles JSON路径（默认: tmp/profiles.json）")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        sys.exit(0)

    if args.cmd == "run":
        cmd_run(args, CONFIG)
    elif args.cmd == "scout":
        cmd_scout(args, CONFIG)
    elif args.cmd == "analyze":
        cmd_analyze(args, CONFIG)
    elif args.cmd == "report":
        cmd_report(args, CONFIG)


def _add_scout_args(p):
    p.add_argument("--min-fans", type=int, help=f"最低粉丝数（默认: {CONFIG['pgy_filters']['min_fans']:,}）")
    p.add_argument("--max-fans", type=int, help=f"最高粉丝数（默认: {CONFIG['pgy_filters']['max_fans']:,}）")
    p.add_argument("--min-interact", type=int, help=f"最低平均互动（默认: {CONFIG['pgy_filters']['min_avg_interact']}）")
    p.add_argument("--max-count", type=int, help=f"最多抓取达人数（默认: {CONFIG['max_candidates']}）")


if __name__ == "__main__":
    main()
