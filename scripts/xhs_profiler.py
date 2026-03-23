"""
小红书达人主页分析模块

对每个候选达人：
1. 访问其小红书主页，抓取基础信息（粉丝数、获赞、笔记数）
2. 抓取最近 N 篇笔记的点赞/评论/收藏数
3. 识别商业合作笔记（带货/品牌合作标签）
4. 识别教育类合作笔记（你的产品目标对标）
5. 计算互动率、稳定性等指标

注意：小红书主页不显示阅读量，只有点赞/评论/收藏。
"""
from __future__ import annotations

import json
import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Optional

CDP_PORT = 9222

# 教育/母婴相关关键词，用于判断笔记是否符合目标受众
EDU_KEYWORDS = [
    "英语", "口语", "外教", "学英语", "英文", "儿童英语", "少儿英语",
    "早教", "启蒙", "教育", "学习", "课程", "网课", "在线课",
    "vipkid", "哒哒", "猿辅导", "作业帮",
]

BABY_KEYWORDS = [
    "母婴", "宝宝", "孩子", "育儿", "亲子", "妈妈", "宝妈",
    "幼儿", "儿童", "小孩", "娃", "宝贝", "幼儿园", "小学",
]

# 商业合作笔记识别关键词
COLLAB_KEYWORDS = [
    "品牌合作", "广告", "合作", "推广", "种草", "测评", "好物",
    "#ad", "sponsored", "赞助",
]

# 教育品牌关键词（判断是否有教育类合作经验）
EDU_BRAND_KEYWORDS = [
    "英语", "教育", "课程", "学习", "外教", "早教", "启蒙", "口语",
    "vipkid", "哒哒", "猿辅导", "核桃", "凯叔",
    "贝乐", "乐读", "流利说", "多邻国",
]


@dataclass
class NoteData:
    note_id: str = ""
    title: str = ""
    likes: int = 0
    comments: int = 0
    collects: int = 0
    total_interact: int = 0
    is_collab: bool = False          # 是否为商业合作笔记
    is_edu_collab: bool = False      # 是否为教育类合作笔记
    is_baby_content: bool = False    # 是否为母婴/育儿内容
    url: str = ""
    note_type: str = ""              # "image" / "video"


@dataclass
class CommentAnalysis:
    """单篇笔记的评论区分析结果"""
    note_id: str = ""
    note_title: str = ""
    total_comments_visible: int = 0   # 可见评论数
    author_reply_count: int = 0       # 博主回复数
    author_reply_rate: float = 0.0    # 博主回复率
    real_comment_ratio: float = 0.0   # 有实质内容的评论占比（排除纯emoji/模板）
    parent_keyword_ratio: float = 0.0 # 评论里含"孩子/宝宝/妈妈"等关键词的比例
    sample_comments: list = field(default_factory=list)  # 评论样本（前5条）
    is_suspicious: bool = False       # 是否疑似刷量（低质量评论占比过高）


@dataclass
class KolProfile:
    # 基础信息
    name: str = ""
    xhs_uid: str = ""
    xhs_url: str = ""
    fans_count: int = 0
    total_likes: int = 0
    notes_count: int = 0
    bio: str = ""
    scout_mode: str = ""             # "targeted" / "breakout"

    # 抓取的笔记数据
    notes: list = field(default_factory=list)
    notes_analyzed: int = 0

    # 互动指标
    avg_likes: float = 0.0
    avg_comments: float = 0.0
    avg_collects: float = 0.0
    avg_interact: float = 0.0
    interact_stability: float = 0.0
    fans_engage_rate: float = 0.0

    # 内容判断
    collab_count: int = 0
    edu_collab_count: int = 0
    baby_content_ratio: float = 0.0

    # 评论区分析
    comment_analyses: list = field(default_factory=list)  # 抽样笔记的评论分析
    avg_author_reply_rate: float = 0.0   # 博主平均回复率
    avg_parent_keyword_ratio: float = 0.0  # 评论中家长相关词占比
    comment_suspicious_count: int = 0     # 疑似刷量笔记数
    comment_quality_score: float = 0.0   # 评论综合质量分 0-10

    # 蒲公英数据
    pgy_price: int = 0
    pgy_category: str = ""

    # 综合评估
    crawl_success: bool = False
    crawl_error: str = ""


# ── CDP helpers（复用pugongying_scout的模式）────────────────────────────────────

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


def human_scroll(page, direction="down", distance=500):
    steps = random.randint(3, 6)
    per_step = distance // steps
    for _ in range(steps):
        delta = per_step * (1 if direction == "down" else -1) * random.uniform(0.8, 1.2)
        page.mouse.wheel(0, delta)
        time.sleep(random.uniform(0.15, 0.4))


def human_read_pause():
    """模拟在看内容时的不均匀停顿：偶尔较长，像真人在读"""
    base = random.uniform(1.5, 5.0)
    if random.random() < 0.12:   # 12%概率停更久（看到有趣内容）
        base += random.uniform(4, 12)
    time.sleep(base)


def rest_between_kols(index: int):
    """博主之间的间隔，每10个额外休息"""
    if index > 0 and index % 10 == 0:
        rest = random.uniform(200, 400)
        print(f"  [大休息] 已处理{index}人，休息 {rest/60:.1f} 分钟...")
        time.sleep(rest)
    else:
        wait = random.uniform(18, 40)
        if random.random() < 0.15:
            wait += random.uniform(15, 30)
        print(f"  等待 {wait:.0f}s...")
        time.sleep(wait)


# ── 评论区抓取与分析 ──────────────────────────────────────────────────────────

# 模板化/低质评论特征（疑似刷量）
SPAM_PATTERNS = [
    r"^[👍❤️🌹💕✨🔥💯🎉😍🥰]+$",   # 纯emoji
    r"^(好棒|太棒了|厉害|666|哈哈+|nice|wow|学习了|收藏了|已收藏|已关注|关注了)$",
    r"^[a-zA-Z]{1,3}$",  # 纯英文字母1-3个
]

# 家长受众关键词
PARENT_KEYWORDS = [
    "孩子", "宝宝", "娃", "小朋友", "儿子", "女儿", "宝贝",
    "妈妈", "爸爸", "家长", "幼儿园", "小学", "英语", "学习",
    "早教", "启蒙", "教育", "课程",
]


def is_spam_comment(text: str) -> bool:
    text = text.strip()
    if len(text) <= 2:
        return True
    for pat in SPAM_PATTERNS:
        if re.match(pat, text, re.UNICODE):
            return True
    return False


def extract_comments_from_note(page, note_url: str, note_title: str = "") -> CommentAnalysis:
    """
    打开一篇笔记，抓取评论区数据。
    分析：博主回复率、评论质量、家长关键词占比。
    """
    result = CommentAnalysis(note_id=note_url.split("/")[-1], note_title=note_title)
    if not note_url:
        return result

    try:
        page.goto(note_url, timeout=20000)
        human_read_pause()  # 模拟阅读笔记正文

        # 滚动到评论区
        human_scroll(page, "down", random.randint(600, 1000))
        time.sleep(random.uniform(1.5, 3))

        # 抓取评论
        comments_data = page.evaluate("""
        () => {
            const items = document.querySelectorAll(
                '[class*="comment-item"], [class*="CommentItem"], ' +
                '.comments-el .parent-comment, [class*="parentComment"]'
            );
            const comments = [];
            items.forEach(item => {
                // 评论内容
                const contentEl = item.querySelector(
                    '[class*="content"], [class*="text"], [class*="desc"]'
                );
                const content = contentEl?.innerText?.trim() || '';

                // 是否是博主回复（找"作者"标签）
                const isAuthor = !!(item.querySelector(
                    '[class*="author"], [class*="Author"], .tag-author, [class*="creator"]'
                ));

                // 点赞数
                const likeEl = item.querySelector('[class*="like"] span, [class*="count"]');
                const likes = parseInt(likeEl?.innerText?.trim() || '0') || 0;

                if (content) {
                    comments.push({ content, isAuthor, likes });
                }
            });
            return comments;
        }
        """) or []

        if not comments_data:
            return result

        result.total_comments_visible = len(comments_data)

        # 统计博主回复
        author_replies = [c for c in comments_data if c.get("isAuthor")]
        non_author = [c for c in comments_data if not c.get("isAuthor")]
        result.author_reply_count = len(author_replies)
        result.author_reply_rate = round(len(author_replies) / max(len(non_author), 1), 3)

        # 评论质量：排除spam
        real_comments = [c for c in non_author if not is_spam_comment(c.get("content", ""))]
        result.real_comment_ratio = round(len(real_comments) / max(len(non_author), 1), 3)

        # 家长关键词占比
        parent_comments = [
            c for c in non_author
            if any(kw in c.get("content", "") for kw in PARENT_KEYWORDS)
        ]
        result.parent_keyword_ratio = round(len(parent_comments) / max(len(non_author), 1), 3)

        # 疑似刷量判断：spam率 > 60% 且总评论数 > 20
        spam_ratio = 1 - result.real_comment_ratio
        result.is_suspicious = spam_ratio > 0.6 and result.total_comments_visible > 20

        # 保存评论样本（前5条非spam非作者）
        result.sample_comments = [
            c["content"][:80] for c in real_comments[:5]
        ]

    except Exception as e:
        result.sample_comments = [f"抓取失败: {e}"]

    return result


def analyze_comments_for_kol(page, notes: list, max_notes_to_check: int = 3) -> list:
    """
    对互动数最高的几篇笔记抓评论区，返回CommentAnalysis列表。
    """
    # 取点赞最高的笔记（最能代表账号真实水平）
    sorted_notes = sorted(notes, key=lambda n: n.get("likes", 0), reverse=True)
    target_notes = [n for n in sorted_notes if n.get("url")][:max_notes_to_check]

    analyses = []
    for i, note in enumerate(target_notes):
        url = note.get("url", "")
        title = note.get("title", "")
        print(f"    评论区 [{i+1}/{len(target_notes)}] {title[:20]}...")

        analysis = extract_comments_from_note(page, url, title)
        analyses.append(asdict(analysis))

        # 评论页之间停顿
        if i < len(target_notes) - 1:
            time.sleep(random.uniform(8, 15))

    return analyses


# ── 主页数据抓取 ──────────────────────────────────────────────────────────────

def parse_count(text: str) -> int:
    """解析 '1.2万' / '3000' / '999+' 等文本"""
    if not text:
        return 0
    text = text.strip().replace("+", "").replace(",", "")
    if "万" in text:
        try:
            return int(float(text.replace("万", "")) * 10000)
        except ValueError:
            return 0
    try:
        return int(float(text))
    except ValueError:
        return 0


def extract_profile_info(page) -> dict:
    """抓取达人基础信息：粉丝数、获赞、笔记数、简介"""
    return page.evaluate("""
    () => {
        // 小红书主页结构：user-info区域
        const getText = (sel) => {
            const el = document.querySelector(sel);
            return el ? el.innerText.trim() : '';
        };

        // 粉丝数 - 多种选择器适配
        let fans = '';
        const fansSelectors = [
            '.user-info .count[data-v-fans]',
            '[class*="fans"] .count',
            '[class*="FansCount"]',
            '.info-container .count',
        ];
        for (const sel of fansSelectors) {
            const el = document.querySelector(sel);
            if (el) { fans = el.innerText.trim(); break; }
        }

        // 通用：找"粉丝"附近的数字
        if (!fans) {
            const items = document.querySelectorAll('.user-info .count, .count-info .count');
            const labels = document.querySelectorAll('.user-info .text, .count-info .text');
            for (let i = 0; i < labels.length; i++) {
                if (labels[i]?.innerText.includes('粉丝') && items[i]) {
                    fans = items[i].innerText.trim();
                    break;
                }
            }
        }

        // 获赞与收藏
        let likes = '';
        const bodyText = document.body.innerText;
        const likeMatch = bodyText.match(/获赞与收藏\\s*([\\d.万]+)/);
        if (likeMatch) likes = likeMatch[1];

        // 简介
        const bio = getText('[class*="desc"], [class*="bio"], .user-desc') ||
                    getText('.user-info .desc');

        // 笔记数（有些主页显示）
        const noteCountMatch = bodyText.match(/笔记\\s*(\\d+)/);
        const notesCount = noteCountMatch ? noteCountMatch[1] : '';

        // 用户名
        const name = getText('[class*="username"], [class*="nickname"], .user-name') ||
                     document.title.split(' - ')[0];

        return { fans, likes, bio, notesCount, name };
    }
    """) or {}


def extract_note_cards(page) -> list:
    """抓取当前可见的笔记卡片数据"""
    return page.evaluate("""
    () => {
        const cards = document.querySelectorAll(
            'section.note-item, [class*="noteItem"], [class*="note-card"], ' +
            '[class*="NoteCard"], .feeds-container section'
        );
        const results = [];
        cards.forEach(card => {
            const titleEl = card.querySelector(
                '[class*="title"], [class*="Title"], .note-desc, footer .title'
            );
            const title = titleEl ? titleEl.innerText.trim() : '';

            // 点赞数
            const likeEl = card.querySelector(
                '[class*="like"] .count, [class*="likes"] span, ' +
                '.interact-info [class*="like"] span, ' +
                'span[class*="likeCount"]'
            );
            const likes = likeEl ? likeEl.innerText.trim() : '0';

            // 链接和noteId
            const linkEl = card.querySelector('a[href*="/explore/"], a[href*="/note/"]');
            const href = linkEl ? linkEl.href : '';
            const noteId = href.match(/\\/(?:explore|note)\\/([a-zA-Z0-9]+)/)?.[1] || '';

            // 类型（视频/图文）
            const isVideo = !!(card.querySelector(
                '[class*="video"], [class*="Video"], .play-icon'
            ));

            // 商业合作标签
            const cardText = card.innerText || '';
            const isCollab = /品牌合作|广告|合作|推广|#ad/i.test(cardText);

            results.push({
                noteId, title, likes,
                url: href,
                noteType: isVideo ? 'video' : 'image',
                isCollab,
                cardText,
            });
        });
        return results;
    }
    """) or []


def classify_note(title: str, card_text: str) -> dict:
    """根据标题和文本判断笔记类型"""
    text = (title + " " + card_text).lower()
    is_edu = any(kw in text for kw in EDU_KEYWORDS)
    is_baby = any(kw in text for kw in BABY_KEYWORDS)
    is_collab = any(kw in text for kw in COLLAB_KEYWORDS)
    is_edu_collab = is_collab and (is_edu or is_baby)
    return {
        "is_edu": is_edu,
        "is_baby": is_baby,
        "is_collab": is_collab,
        "is_edu_collab": is_edu_collab,
    }


def profile_one_kol(page, xhs_url: str, notes_to_analyze: int = 20, screenshot_dir: str = "tmp/screenshots") -> KolProfile:
    """
    访问一个达人主页，完整分析并返回KolProfile。
    """
    profile = KolProfile(xhs_url=xhs_url)
    uid_match = xhs_url.split("/user/profile/")
    profile.xhs_uid = uid_match[1].split("?")[0] if len(uid_match) > 1 else ""

    try:
        page.goto(xhs_url, timeout=20000)
        time.sleep(random.uniform(2, 3.5))

        # 抓基础信息
        info = extract_profile_info(page)
        profile.name = info.get("name", "")
        profile.fans_count = parse_count(info.get("fans", "0"))
        profile.total_likes = parse_count(info.get("likes", "0"))
        profile.bio = info.get("bio", "")[:200]
        profile.notes_count = parse_count(info.get("notesCount", "0"))

        # 截图
        safe_name = re.sub(r"[^\w]", "_", profile.name or profile.xhs_uid)[:20]
        page.screenshot(path=os.path.join(screenshot_dir, f"kol_{safe_name}.png"))

        # 滚动抓笔记，模拟真人浏览节奏
        all_notes_raw = []
        seen_ids = set()

        for scroll_i in range(8):
            cards = extract_note_cards(page)
            for card in cards:
                nid = card.get("noteId", "")
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    all_notes_raw.append(card)

            if len(all_notes_raw) >= notes_to_analyze:
                break

            # 不均匀滚动：有时快翻，有时停下来"看"
            scroll_dist = random.randint(300, 800)
            human_scroll(page, "down", scroll_dist)

            # 偶尔停下来阅读
            if random.random() < 0.4:
                human_read_pause()
            else:
                time.sleep(random.uniform(1.0, 2.5))

        # 解析笔记数据
        notes = []
        for raw in all_notes_raw[:notes_to_analyze]:
            title = raw.get("title", "")
            card_text = raw.get("cardText", "")
            clf = classify_note(title, card_text)

            note = NoteData(
                note_id=raw.get("noteId", ""),
                title=title,
                likes=parse_count(raw.get("likes", "0")),
                url=raw.get("url", ""),
                note_type=raw.get("noteType", "image"),
                is_collab=raw.get("isCollab", False) or clf["is_collab"],
                is_edu_collab=clf["is_edu_collab"],
                is_baby_content=clf["is_baby"],
            )
            note.total_interact = note.likes + note.comments + note.collects
            notes.append(note)

        profile.notes = [asdict(n) for n in notes]
        profile.notes_analyzed = len(notes)

        # 计算笔记互动指标
        if notes:
            likes_list = [n.likes for n in notes]
            interact_list = [n.total_interact for n in notes]

            profile.avg_likes = round(sum(likes_list) / len(likes_list), 1)
            profile.avg_interact = round(sum(interact_list) / len(interact_list), 1)
            profile.collab_count = sum(1 for n in notes if n.is_collab)
            profile.edu_collab_count = sum(1 for n in notes if n.is_edu_collab)
            baby_count = sum(1 for n in notes if n.is_baby_content)
            profile.baby_content_ratio = round(baby_count / len(notes), 2)

            if profile.avg_likes > 0:
                profile.interact_stability = round(min(likes_list) / profile.avg_likes, 2)
            if profile.fans_count > 0:
                profile.fans_engage_rate = round(profile.avg_likes / profile.fans_count * 100, 3)

        # ── 评论区分析（抽3篇高赞笔记）──────────────────────────────────────
        print(f"    分析评论区...")
        note_dicts = [asdict(n) for n in notes]
        comment_analyses = analyze_comments_for_kol(page, note_dicts, max_notes_to_check=3)
        profile.comment_analyses = comment_analyses

        if comment_analyses:
            valid_ca = [ca for ca in comment_analyses if ca.get("total_comments_visible", 0) > 0]
            if valid_ca:
                profile.avg_author_reply_rate = round(
                    sum(ca["author_reply_rate"] for ca in valid_ca) / len(valid_ca), 3)
                profile.avg_parent_keyword_ratio = round(
                    sum(ca["parent_keyword_ratio"] for ca in valid_ca) / len(valid_ca), 3)
                profile.comment_suspicious_count = sum(
                    1 for ca in valid_ca if ca.get("is_suspicious"))

                # 评论质量综合分 0-10
                # 构成：真实评论率(4分) + 博主回复率(3分) + 家长关键词占比(3分)
                avg_real = sum(ca["real_comment_ratio"] for ca in valid_ca) / len(valid_ca)
                profile.comment_quality_score = round(
                    avg_real * 4 +
                    min(profile.avg_author_reply_rate * 6, 3) +  # 回复率50%=满3分
                    min(profile.avg_parent_keyword_ratio * 10, 3),  # 30%=满3分
                    2
                )

        # 回到主页（评论分析完需要返回）
        page.goto(xhs_url, timeout=20000)
        time.sleep(random.uniform(2, 3))

        profile.crawl_success = True

    except Exception as e:
        profile.crawl_error = str(e)
        print(f"    [错误] {xhs_url}: {e}")

    return profile


# ── 批量分析 ──────────────────────────────────────────────────────────────────

def run_profiler(
    candidates_path: str = "tmp/candidates.json",
    output_path: str = "tmp/profiles.json",
    notes_per_kol: int = 20,
    screenshot_dir: str = "tmp/screenshots",
    delay_between: tuple = (3, 6),
) -> list:
    """
    读取候选名单，逐一访问小红书主页分析，保存结果。
    """
    if not os.path.exists(candidates_path):
        print(f"[错误] 候选名单不存在: {candidates_path}")
        return []

    with open(candidates_path, encoding="utf-8") as f:
        candidates = json.load(f)

    # 过滤没有xhs_url的
    valid = [c for c in candidates if c.get("xhs_url")]
    skipped = len(candidates) - len(valid)
    if skipped:
        print(f"[警告] {skipped} 个达人没有小红书链接，跳过")

    print("=" * 60)
    print(f"小红书主页分析：共 {len(valid)} 个达人")
    print("=" * 60)

    os.makedirs(screenshot_dir, exist_ok=True)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    pw, browser, page = connect_cdp()
    profiles = []

    try:
        for i, c in enumerate(valid):
            name = c.get("name", f"达人{i+1}")
            url = c["xhs_url"]
            print(f"\n[{i+1}/{len(valid)}] {name} — {url}")

            profile = profile_one_kol(page, url, notes_per_kol, screenshot_dir)

            # 补充蒲公英和来源数据
            profile.pgy_price = c.get("avg_price", 0)
            profile.pgy_category = c.get("category", "")
            profile.scout_mode = c.get("scout_mode", "targeted")
            if not profile.name:
                profile.name = name

            profiles.append(asdict(profile))

            # 进度汇报
            if profile.crawl_success:
                print(f"  ✓ 粉丝:{profile.fans_count:,}  均赞:{profile.avg_likes:.0f}  "
                      f"互动率:{profile.fans_engage_rate:.2f}%  "
                      f"母婴:{profile.baby_content_ratio*100:.0f}%  "
                      f"教育合作:{profile.edu_collab_count}  "
                      f"评论质量:{profile.comment_quality_score:.1f}/10  "
                      f"疑似刷量:{profile.comment_suspicious_count}篇")
            else:
                print(f"  ✗ 失败: {profile.crawl_error}")

            # 实时保存
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(profiles, f, ensure_ascii=False, indent=2)

            # 慢速停顿
            if i < len(valid) - 1:
                rest_between_kols(i + 1)

    finally:
        pw.stop()

    print(f"\n[完成] 分析结果保存至: {output_path}")
    success = sum(1 for p in profiles if p.get("crawl_success"))
    print(f"  成功: {success}/{len(valid)}")
    return profiles


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="tmp/candidates.json")
    p.add_argument("--output", default="tmp/profiles.json")
    p.add_argument("--notes", type=int, default=20)
    args = p.parse_args()

    run_profiler(candidates_path=args.input, output_path=args.output, notes_per_kol=args.notes)
