"""
蒲公英达人初筛模块

通过CDP连接已登录的Chrome，在蒲公英后台按条件筛选达人，
逐一访问达人主页，判断是否符合条件，输出候选名单JSON。

前提：Chrome已启动，已登录 https://www.pgyapp.com 蒲公英达人后台
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

CDP_PORT = 9222
PGYAPP_URL = "https://pgy.xiaohongshu.com/solar/pre-trade/note/kol"

# ── 两套筛选策略 ──────────────────────────────────────────────────────────────
# 定向：母婴/教育类目，受众精准
FILTERS_TARGETED = {
    "mode": "targeted",
    "label": "定向母婴/教育",
    "min_fans": 10_000,
    "max_fans": 500_000,
    "min_avg_interact": 100,
    # 蒲公英页面需手动点选的类目（脚本会在页面上点击）
    "pgy_categories": ["母婴", "教育"],
    # 粉丝年龄段筛选（蒲公英支持）- 用于JS点选
    "fan_age": "25-40",
}

# 破圈：泛类目，靠受众年龄段+教育合作历史来过滤
FILTERS_BREAKOUT = {
    "mode": "breakout",
    "label": "破圈泛类目",
    "min_fans": 20_000,
    "max_fans": 1_000_000,
    "min_avg_interact": 300,
    # 覆盖受众可能有家长的类目
    "pgy_categories": ["科技数码", "职场", "生活记录", "文化艺术", "兴趣爱好", "健康养生"],
    "fan_age": "25-40",
}

DEFAULT_FILTERS = FILTERS_TARGETED  # 默认用定向


@dataclass
class PgyCandidate:
    name: str = ""
    pgy_uid: str = ""
    xhs_uid: str = ""
    xhs_url: str = ""
    fans_count: int = 0
    category: str = ""
    avg_price: int = 0
    avg_interact: int = 0
    cooperation_count: int = 0
    pgy_profile_url: str = ""
    raw: dict = field(default_factory=dict)


# ── CDP helpers ───────────────────────────────────────────────────────────────

def connect_cdp():
    from playwright.sync_api import sync_playwright
    os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost")
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{CDP_PORT}")
    ctx = browser.contexts[0]
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return pw, browser, page


def _bezier(t, p0, p1, p2, p3):
    u = 1 - t
    return u**3*p0 + 3*u**2*t*p1 + 3*u*t**2*p2 + t**3*p3


def human_move(page, to_x, to_y, from_x=640, from_y=450):
    dx, dy = to_x - from_x, to_y - from_y
    dist = math.sqrt(dx*dx + dy*dy)
    steps = max(8, min(25, int(dist / 20)))
    perp_x = -dy / max(dist, 1)
    perp_y = dx / max(dist, 1)
    curve = random.uniform(-0.2, 0.2) * dist
    cp1x = from_x + dx*0.25 + perp_x*curve*random.uniform(0.5, 1.5)
    cp1y = from_y + dy*0.25 + perp_y*curve*random.uniform(0.5, 1.5)
    cp2x = from_x + dx*0.75 + perp_x*curve*random.uniform(0.3, 0.8)
    cp2y = from_y + dy*0.75 + perp_y*curve*random.uniform(0.3, 0.8)
    for i in range(steps + 1):
        t = i / steps
        te = t*t*(3 - 2*t)
        x = _bezier(te, from_x, cp1x, cp2x, to_x)
        y = _bezier(te, from_y, cp1y, cp2y, to_y)
        page.mouse.move(x, y)
        time.sleep(random.uniform(0.005, 0.015))


def human_click(page, x, y):
    human_move(page, x, y)
    time.sleep(random.uniform(0.08, 0.2))
    page.mouse.click(x, y)
    time.sleep(random.uniform(0.3, 0.8))


def natural_scroll(page, direction="down", distance=600):
    steps = random.randint(4, 8)
    per_step = distance // steps
    for _ in range(steps):
        delta = per_step * (1 if direction == "down" else -1)
        page.mouse.wheel(0, delta * random.uniform(0.8, 1.2))
        time.sleep(random.uniform(0.1, 0.35))


def human_pause(min_s=1.5, max_s=4.0, reason=""):
    """模拟人类阅读/思考停顿，偶尔有更长停顿"""
    base = random.uniform(min_s, max_s)
    # 10%概率出现较长停顿（模拟走神/看手机）
    if random.random() < 0.10:
        base += random.uniform(3, 8)
    if reason:
        pass  # 不打印，保持安静
    time.sleep(base)


def rest_between_kols(kol_index: int):
    """每处理N个博主后休息更长时间"""
    # 每10个博主休息3-6分钟
    if kol_index > 0 and kol_index % 10 == 0:
        rest = random.uniform(180, 360)
        print(f"  [休息] 已处理{kol_index}个博主，休息 {rest/60:.1f} 分钟...")
        time.sleep(rest)
    else:
        # 正常间隔：15-35秒，不均匀
        wait = random.uniform(15, 35)
        # 偶尔更长
        if random.random() < 0.15:
            wait += random.uniform(10, 25)
        print(f"  等待 {wait:.0f}s...")
        time.sleep(wait)


# ── 蒲公英数据抓取 ─────────────────────────────────────────────────────────────

def parse_fan_count(text: str) -> int:
    text = text.strip().replace(",", "")
    if "万" in text:
        return int(float(text.replace("万", "")) * 10000)
    if "w" in text.lower():
        return int(float(text.lower().replace("w", "")) * 10000)
    try:
        return int(float(text))
    except ValueError:
        return 0


def extract_talent_cards(page) -> list:
    """从蒲公英笔记博主广场提取当前可见的博主行数据（适配真实DOM结构）"""
    result = page.evaluate("""
    () => {
        const rows = document.querySelectorAll('table tbody tr');
        const data = [];
        rows.forEach(row => {
            const cells = row.querySelectorAll('td');
            if (cells.length < 4) return;

            // 第1列：博主信息
            const infoCell = cells[0]?.innerText?.trim() || '';
            const lines = infoCell.split('\\n').map(l => l.trim()).filter(Boolean);
            const name = lines[0] || '';
            if (!name) return;

            // 跳过骨架屏加载行
            if (row.querySelector('[class*="skeleton"]')) return;

            // 地区（第2行通常是地区）
            const region = lines[1] || '';

            // 标签（从info cell提取，去除重复）
            const tagEls = cells[0]?.querySelectorAll('[class*="tag"], [class*="label"]') || [];
            const tags = [...new Set(Array.from(tagEls).map(t => t.innerText.trim()).filter(Boolean))].join(',');

            // 期待合作行业
            const wantCollab = infoCell.includes('期待与') ?
                infoCell.match(/期待与「(.+?)」/)?.[1] || '' : '';

            // 第3列：粉丝数
            const fans = cells[2]?.innerText?.trim() || '';

            // 第4列：阅读中位数
            const readMedian = cells[3]?.innerText?.trim() || '';

            // 第5列：互动中位数
            const interactMedian = cells[4]?.innerText?.trim() || '';

            // 第6列：报价
            const price = (cells[5]?.innerText?.trim() || '').replace(/\\n/g, '').replace('起', '').trim();

            // 博主主页链接（通过data属性或点击跳转）
            const link = row.querySelector('a')?.href || '';

            data.push({ name, region, tags, wantCollab, fans, readMedian, interactMedian, price, link });
        });
        return data;
    }
    """)
    return result or []


def scrape_pgy_page(page, filters: dict) -> list:
    candidates = []
    raw_cards = extract_talent_cards(page)

    if not raw_cards:
        return candidates

    for card in raw_cards:
        fans = parse_fan_count(card.get("fans", "0"))
        if fans < filters.get("min_fans", 0) or fans > filters.get("max_fans", 9_999_999):
            continue

        # 报价：¥7,000 → 7000
        price_text = card.get("price", "0").replace("¥", "").replace(",", "").strip()
        digits = "".join(c for c in price_text if c.isdigit() or c == ".")
        try:
            price = int(float(digits)) if digits else 0
        except ValueError:
            price = 0

        # 互动中位数
        interact_text = card.get("interactMedian", "0").replace(",", "").strip()
        digits2 = "".join(c for c in interact_text if c.isdigit() or c == ".")
        try:
            interact = int(float(digits2)) if digits2 else 0
        except ValueError:
            interact = 0

        if interact < filters.get("min_avg_interact", 0):
            continue

        c = PgyCandidate(
            name=card.get("name", ""),
            fans_count=fans,
            category=card.get("tags", ""),
            avg_price=price,
            avg_interact=interact,
            pgy_profile_url=card.get("link", ""),
            raw=card,
        )
        candidates.append(c)

    return candidates


def get_xhs_url_from_pgy_profile(page, pgy_url: str) -> str:
    """访问蒲公英达人详情页，提取小红书主页链接"""
    if not pgy_url:
        return ""
    try:
        page.goto(pgy_url, timeout=15000)
        time.sleep(random.uniform(1.5, 2.5))

        xhs_url = page.evaluate("""
        () => {
            const links = Array.from(document.querySelectorAll('a'));
            for (const a of links) {
                if (a.href && a.href.includes('xiaohongshu.com/user/profile')) {
                    return a.href;
                }
            }
            const text = document.body.innerText;
            const match = text.match(/xiaohongshu\\.com\\/user\\/profile\\/([a-f0-9]{24})/i);
            return match ? 'https://www.xiaohongshu.com/user/profile/' + match[1] : '';
        }
        """)
        return xhs_url or ""
    except Exception as e:
        print(f"  [警告] 获取小红书链接失败: {e}")
        return ""


# ── 蒲公英筛选条件设置 ────────────────────────────────────────────────────────

def apply_pgy_filters(page, filters: dict, screenshot_dir: str):
    """在蒲公英页面上点选类目、粉丝年龄等筛选条件"""
    # 先重置到全部类目
    try:
        reset = page.query_selector('text=重置, text=清空, [class*="reset"]')
        if reset:
            reset.click()
            time.sleep(random.uniform(1, 2))
    except Exception:
        pass

    # 点选类目
    categories = filters.get("pgy_categories", [])
    for cat in categories:
        try:
            el = page.query_selector(f'text={cat}')
            if el:
                bbox = el.bounding_box()
                if bbox:
                    human_click(page, bbox["x"] + bbox["width"]/2, bbox["y"] + bbox["height"]/2)
                    time.sleep(random.uniform(0.8, 1.5))
                    print(f"  [筛选] 已选类目: {cat}")
        except Exception as e:
            print(f"  [筛选] 点选 {cat} 失败: {e}")

    # 截图确认筛选结果
    time.sleep(random.uniform(1.5, 2.5))
    page.screenshot(path=os.path.join(screenshot_dir, f"pgy_filter_{filters.get('mode','')}.png"))


# ── 主流程 ─────────────────────────────────────────────────────────────────────

def run_scout(
    filters: Optional[dict] = None,
    max_candidates: int = 50,
    output_path: str = "tmp/candidates.json",
    screenshot_dir: str = "tmp/screenshots",
) -> list:
    filters = {**DEFAULT_FILTERS, **(filters or {})}
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    os.makedirs(screenshot_dir, exist_ok=True)

    print("=" * 60)
    print("蒲公英达人初筛")
    print(f"  粉丝范围: {filters['min_fans']//10000}万 - {filters['max_fans']//10000}万")
    print(f"  最低平均互动: {filters['min_avg_interact']}")
    print(f"  最多抓取: {max_candidates} 人")
    print("=" * 60)

    pw, browser, page = connect_cdp()
    all_candidates: list = []

    try:
        print(f"\n[蒲公英] 导航到达人广场...")
        page.goto(PGYAPP_URL, timeout=20000)
        time.sleep(random.uniform(2, 3))
        page.screenshot(path=os.path.join(screenshot_dir, "pgy_01_initial.png"))
        print(f"[蒲公英] 初始截图已保存，确认页面已登录")

        page_num = 1
        while len(all_candidates) < max_candidates:
            print(f"\n[蒲公英] 第 {page_num} 页...")
            time.sleep(random.uniform(1, 2))

            candidates = scrape_pgy_page(page, filters)
            print(f"  → 符合条件: {len(candidates)} 个")

            if not candidates:
                page.screenshot(path=os.path.join(screenshot_dir, f"pgy_debug_p{page_num}.png"))
                print(f"  [警告] 未抓到数据，截图保存至 {screenshot_dir}/pgy_debug_p{page_num}.png")
                print("  请检查：1) 是否已登录蒲公英  2) 页面结构是否变化")
                break

            all_candidates.extend(candidates)

            # 翻页
            try:
                next_btn = page.query_selector(
                    '.el-pagination .btn-next, '
                    'button[class*="next"], '
                    '[class*="pagination"] [class*="next"]'
                )
                if next_btn and next_btn.is_enabled():
                    bbox = next_btn.bounding_box()
                    if bbox:
                        human_click(page, bbox["x"] + bbox["width"]/2, bbox["y"] + bbox["height"]/2)
                        time.sleep(random.uniform(1.5, 2.5))
                        page_num += 1
                    else:
                        break
                else:
                    print("[蒲公英] 已到末页")
                    break
            except Exception as e:
                print(f"[蒲公英] 翻页出错: {e}")
                break

        # 去重 + 截取
        seen, deduped = set(), []
        for c in all_candidates:
            key = c.pgy_uid or c.name
            if key and key not in seen:
                seen.add(key)
                deduped.append(c)
        all_candidates = deduped[:max_candidates]

        print(f"\n[蒲公英] 初筛完成：{len(all_candidates)} 人")
        print("[蒲公英] 正在获取各达人的小红书链接...")

        for i, c in enumerate(all_candidates):
            if c.pgy_profile_url and not c.xhs_url:
                print(f"  [{i+1}/{len(all_candidates)}] {c.name} ...")
                xhs_url = get_xhs_url_from_pgy_profile(page, c.pgy_profile_url)
                c.xhs_url = xhs_url
                uid_match = xhs_url.split("/user/profile/")
                c.xhs_uid = uid_match[1].split("?")[0] if len(uid_match) > 1 else ""
                if not xhs_url:
                    print(f"    [未找到小红书链接]")

        data = [asdict(c) for c in all_candidates]
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n[蒲公英] 候选名单保存至: {output_path}")

    finally:
        pw.stop()

    return all_candidates


def run_scout_dual(
    max_per_round: int = 50,
    output_path: str = "tmp/candidates.json",
    screenshot_dir: str = "tmp/screenshots",
) -> list:
    """
    双轮筛选：先跑定向（母婴/教育），再跑破圈（泛类目），合并去重输出。
    """
    print("\n" + "="*60)
    print("双轮筛选模式")
    print("  第一轮：定向母婴/教育")
    print("  第二轮：破圈泛类目（科技/职场/生活等）")
    print("="*60)

    # 第一轮
    print("\n【第一轮】定向筛选...")
    r1_path = output_path.replace(".json", "_targeted.json")
    round1 = run_scout(filters=FILTERS_TARGETED, max_candidates=max_per_round,
                       output_path=r1_path, screenshot_dir=screenshot_dir)

    # 两轮之间休息
    rest = random.uniform(60, 120)
    print(f"\n两轮之间休息 {rest:.0f}s...")
    time.sleep(rest)

    # 第二轮
    print("\n【第二轮】破圈筛选...")
    r2_path = output_path.replace(".json", "_breakout.json")
    round2 = run_scout(filters=FILTERS_BREAKOUT, max_candidates=max_per_round,
                       output_path=r2_path, screenshot_dir=screenshot_dir)

    # 合并去重
    seen, merged = set(), []
    for c in round1 + round2:
        key = (c.name if hasattr(c, 'name') else c.get('name', ''))
        if key and key not in seen:
            seen.add(key)
            merged.append(c if isinstance(c, dict) else asdict(c))

    # 给破圈达人加标记
    targeted_names = {c.name if hasattr(c, 'name') else c.get('name', '') for c in round1}
    for c in merged:
        name = c.get('name', '')
        c['scout_mode'] = 'targeted' if name in targeted_names else 'breakout'

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"\n合并完成：定向 {len(round1)} + 破圈 {len(round2)} = 共 {len(merged)} 人（已去重）")
    print(f"候选名单保存至: {output_path}")
    return merged


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["targeted", "breakout", "dual"], default="dual")
    p.add_argument("--min-fans", type=int, default=None)
    p.add_argument("--max-fans", type=int, default=None)
    p.add_argument("--min-interact", type=int, default=None)
    p.add_argument("--max", type=int, default=50, dest="max_count")
    p.add_argument("--output", default="tmp/candidates.json")
    args = p.parse_args()

    if args.mode == "dual":
        run_scout_dual(max_per_round=args.max_count, output_path=args.output)
    else:
        base = FILTERS_TARGETED if args.mode == "targeted" else FILTERS_BREAKOUT
        overrides = {}
        if args.min_fans: overrides["min_fans"] = args.min_fans
        if args.max_fans: overrides["max_fans"] = args.max_fans
        if args.min_interact: overrides["min_avg_interact"] = args.min_interact
        run_scout(filters={**base, **overrides}, max_candidates=args.max_count, output_path=args.output)
