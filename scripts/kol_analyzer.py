"""
KOL评级和报告生成模块

产品背景：请在 config.py 中配置你的产品信息
目标用户：请在 config.py 中配置
CPM预算：请在 config.py 中配置（默认30元）
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── 评级规则 ──────────────────────────────────────────────────────────────────

# CPM预算（元），用于反推建议报价上限
CPM_BUDGET = 30.0

# KOL 受众匹配评分权重（总分100）
SCORING_WEIGHTS = {
    "audience_match": 30,       # 受众匹配度（最重要：找对人）
    "edu_collab_exp": 25,       # 有教育类合作经验（找对人）
    "price_efficiency": 20,     # 报价性价比（花对钱）
    "fans_engage_rate": 15,     # 互动率（数据真实性验证）
    "comment_quality": 5,       # 评论区质量（辅助验证）
    "stability": 5,             # 互动稳定性（辅助验证）
}


@dataclass
class KolRating:
    name: str = ""
    xhs_url: str = ""
    grade: str = ""              # S / A / B / C / D
    score: float = 0.0           # 0-100综合分
    recommend: bool = False

    fans_count: int = 0
    avg_likes: float = 0.0
    fans_engage_rate: float = 0.0
    interact_stability: float = 0.0

    pgy_price: int = 0           # 蒲公英报价
    suggested_price: int = 0     # 建议报价（基于CPM预算）
    estimated_cpm: float = 0.0   # 按蒲公英报价估算的CPM

    edu_collab_count: int = 0
    baby_content_ratio: float = 0.0
    collab_count: int = 0

    # 评级分项
    score_engage: float = 0.0
    score_audience: float = 0.0
    score_edu_exp: float = 0.0
    score_comment: float = 0.0
    score_stability: float = 0.0
    score_price: float = 0.0

    # 评论区数据
    comment_quality_score: float = 0.0
    avg_author_reply_rate: float = 0.0
    avg_parent_keyword_ratio: float = 0.0
    comment_suspicious_count: int = 0
    comment_samples: list = field(default_factory=list)  # 真实评论样本

    # 来源
    scout_mode: str = ""   # "targeted" / "breakout"

    # 建联话术
    outreach_script: str = ""

    # 评级依据说明
    reason: str = ""

    # 教育合作笔记示例
    edu_collab_examples: list = field(default_factory=list)


# ── 评分函数 ──────────────────────────────────────────────────────────────────

def score_engage_rate(rate: float) -> float:
    """互动率评分（满分15）"""
    if rate >= 3.0:
        return 15.0
    elif rate >= 2.0:
        return 13.0
    elif rate >= 1.0:
        return 10.0
    elif rate >= 0.5:
        return 6.0
    elif rate >= 0.2:
        return 3.0
    else:
        return 0.0


def score_audience_match(baby_ratio: float, category: str, bio: str) -> float:
    """受众匹配度评分（满分30）
    判断达人受众是否是有孩子的家长：内容占比 + 账号分类 + 简介信号 + 评论家长词
    """
    score = 0.0
    bio_text = (bio or "").lower()
    cat_text = (category or "").lower()

    # 母婴/亲子内容占比（最高18分）
    if baby_ratio >= 0.6:
        score += 18
    elif baby_ratio >= 0.3:
        score += 13
    elif baby_ratio >= 0.1:
        score += 7
    elif baby_ratio > 0:
        score += 3

    # 账号分类标签（最高8分）
    baby_cats = ["母婴", "亲子", "育儿", "家庭", "宝妈"]
    edu_cats = ["教育", "学习", "科技", "职场"]
    if any(k in cat_text for k in baby_cats):
        score += 8
    elif any(k in cat_text for k in edu_cats):
        score += 5

    # 简介信号（最高4分）
    bio_signals = ["妈妈", "宝妈", "两娃", "孩子", "育儿", "宝宝", "孩子他妈", "带娃"]
    if any(k in bio_text for k in bio_signals):
        score += 4

    return min(score, 30.0)


def score_edu_experience(edu_collab_count: int, total_notes: int) -> float:
    """教育类合作经验评分（满分25）"""
    if edu_collab_count >= 3:
        return 25.0
    elif edu_collab_count == 2:
        return 18.0
    elif edu_collab_count == 1:
        return 12.0
    else:
        return 0.0


def score_comment_quality(
    quality_score: float,
    suspicious_count: int,
    author_reply_rate: float,
    parent_ratio: float,
) -> float:
    """评论区质量评分（满分5）辅助验证"""
    base = min(quality_score / 10 * 3, 3.0)

    if author_reply_rate >= 0.1:
        base += 1.0

    if parent_ratio >= 0.15:
        base += 1.0

    if suspicious_count >= 2:
        base -= 3.0
    elif suspicious_count == 1:
        base -= 1.0

    return max(0.0, min(base, 5.0))


def score_stability(stability: float) -> float:
    """互动稳定性评分（满分5）"""
    if stability >= 0.5:
        return 5.0
    elif stability >= 0.3:
        return 3.5
    elif stability >= 0.15:
        return 2.0
    else:
        return 0.5


def score_price_efficiency(pgy_price: int, fans_count: int, avg_likes: float, cpm_budget: float) -> tuple:
    """报价性价比评分（满分20），返回 (score, estimated_cpm, suggested_price)"""
    if pgy_price <= 0 or avg_likes <= 0:
        return 10.0, 0.0, 0  # 无报价数据，给中性分

    # 用平均点赞*10粗估预期播放（小红书无阅读量，用点赞做代理指标）
    # 经验比例：小红书点赞/播放 约 3-8%，取5%
    estimated_views = avg_likes / 0.05
    if estimated_views <= 0:
        return 5.0, 0.0, pgy_price

    estimated_cpm = pgy_price / (estimated_views / 1000)

    # 建议报价 = CPM预算 * 预估播放 / 1000
    suggested_price = int(cpm_budget * estimated_views / 1000)

    if estimated_cpm <= cpm_budget * 0.5:
        return 20.0, estimated_cpm, suggested_price
    elif estimated_cpm <= cpm_budget:
        return 16.0, estimated_cpm, suggested_price
    elif estimated_cpm <= cpm_budget * 1.5:
        return 10.0, estimated_cpm, suggested_price
    elif estimated_cpm <= cpm_budget * 2:
        return 4.0, estimated_cpm, suggested_price
    else:
        return 0.0, estimated_cpm, suggested_price


def grade_from_score(score: float) -> str:
    if score >= 80:
        return "S"
    elif score >= 65:
        return "A"
    elif score >= 50:
        return "B"
    elif score >= 35:
        return "C"
    else:
        return "D"


def build_reason(r: KolRating) -> str:
    parts = []

    # 互动率评价
    if r.fans_engage_rate >= 2.0:
        parts.append(f"互动率{r.fans_engage_rate:.2f}%（优秀）")
    elif r.fans_engage_rate >= 1.0:
        parts.append(f"互动率{r.fans_engage_rate:.2f}%（良好）")
    elif r.fans_engage_rate >= 0.5:
        parts.append(f"互动率{r.fans_engage_rate:.2f}%（一般）")
    else:
        parts.append(f"互动率{r.fans_engage_rate:.2f}%（偏低）")

    # 受众匹配
    if r.baby_content_ratio >= 0.3:
        parts.append(f"母婴/亲子内容占{r.baby_content_ratio*100:.0f}%，受众匹配度高")
    elif r.baby_content_ratio > 0:
        parts.append(f"有少量育儿内容（{r.baby_content_ratio*100:.0f}%），受众有一定重叠")

    # 教育合作经验
    if r.edu_collab_count > 0:
        examples = "、".join(r.edu_collab_examples[:2])
        parts.append(f"有{r.edu_collab_count}篇教育类合作笔记（如：{examples}）")
    else:
        parts.append("暂未发现教育类合作记录")

    # 稳定性
    if r.interact_stability >= 0.3:
        parts.append("互动数据稳定")
    elif r.interact_stability < 0.15:
        parts.append("互动波动较大，注意数据真实性")

    # 报价
    if r.pgy_price > 0:
        if r.estimated_cpm > 0:
            cpm_eval = "合理" if r.estimated_cpm <= CPM_BUDGET else "偏高"
            parts.append(f"蒲公英报价¥{r.pgy_price}（估算CPM={r.estimated_cpm:.1f}，{cpm_eval}，建议报价¥{r.suggested_price}）")
        else:
            parts.append(f"蒲公英报价¥{r.pgy_price}")

    return "；".join(parts)


def build_outreach_script(r: KolRating) -> str:
    """根据达人数据生成个性化建联话术"""
    name = r.name or "您好"

    if r.edu_collab_count > 0:
        # 有教育合作经验：直接对标
        return (
            f"您好{name}～ 看到您之前合作过教育类品牌，笔记互动效果很不错！"
            f"我们是【你的品牌】，"
            f"目前在找有真实宝妈粉丝的博主合作，"
            f"您的粉丝群体和我们的用户非常吻合。"
            f"想了解一下您最近是否有档期，合作形式灵活，欢迎聊聊～"
        )
    elif r.baby_content_ratio >= 0.3:
        # 母婴账号但无教育合作
        return (
            f"您好{name}～ 看了您分享的育儿内容，感觉很有共鸣！"
            f"我们是【你的品牌】，产品非常适合您的粉丝群体，"
            f"很多用户反馈效果很好。"
            f"想和您探讨下合作可能性，方便的话可以给您发个免费体验课先感受一下？"
        )
    else:
        # 泛生活类但受众有重叠
        return (
            f"您好{name}～ 关注您很久了，内容质量很高！"
            f"我们是【你的品牌】，"
            f"判断您的粉丝中有不少有孩子的家长，"
            f"想了解下您是否接受教育品类的合作～"
        )


# ── 主评级函数 ────────────────────────────────────────────────────────────────

def analyze_profile(profile: dict) -> KolRating:
    r = KolRating(
        name=profile.get("name", ""),
        xhs_url=profile.get("xhs_url", ""),
        fans_count=profile.get("fans_count", 0),
        avg_likes=profile.get("avg_likes", 0),
        fans_engage_rate=profile.get("fans_engage_rate", 0),
        interact_stability=profile.get("interact_stability", 0),
        pgy_price=profile.get("pgy_price", 0),
        edu_collab_count=profile.get("edu_collab_count", 0),
        baby_content_ratio=profile.get("baby_content_ratio", 0),
        collab_count=profile.get("collab_count", 0),
        comment_quality_score=profile.get("comment_quality_score", 0),
        avg_author_reply_rate=profile.get("avg_author_reply_rate", 0),
        avg_parent_keyword_ratio=profile.get("avg_parent_keyword_ratio", 0),
        comment_suspicious_count=profile.get("comment_suspicious_count", 0),
        scout_mode=profile.get("scout_mode", "targeted"),
    )

    # 提取评论样本
    for ca in profile.get("comment_analyses", []):
        r.comment_samples.extend(ca.get("sample_comments", []))
    r.comment_samples = r.comment_samples[:5]

    # 提取教育合作笔记示例
    notes = profile.get("notes", [])
    r.edu_collab_examples = [
        n["title"] for n in notes
        if n.get("is_edu_collab") and n.get("title")
    ][:3]

    # 各维度评分
    r.score_engage = score_engage_rate(r.fans_engage_rate)
    r.score_audience = score_audience_match(
        r.baby_content_ratio,
        profile.get("pgy_category", ""),
        profile.get("bio", ""),
    )
    r.score_edu_exp = score_edu_experience(r.edu_collab_count, len(notes))
    r.score_comment = score_comment_quality(
        r.comment_quality_score,
        r.comment_suspicious_count,
        r.avg_author_reply_rate,
        r.avg_parent_keyword_ratio,
    )
    r.score_stability = score_stability(r.interact_stability)
    price_score, r.estimated_cpm, r.suggested_price = score_price_efficiency(
        r.pgy_price, r.fans_count, r.avg_likes, CPM_BUDGET
    )
    r.score_price = price_score

    r.score = round(
        r.score_engage + r.score_audience + r.score_edu_exp +
        r.score_comment + r.score_stability + r.score_price,
        1
    )
    r.grade = grade_from_score(r.score)
    r.recommend = r.grade in ("S", "A")

    r.reason = build_reason(r)
    r.outreach_script = build_outreach_script(r)

    return r


# ── 报告生成 ──────────────────────────────────────────────────────────────────

def generate_report(
    profiles_path: str = "tmp/profiles.json",
    output_dir: str = "output",
) -> str:
    if not os.path.exists(profiles_path):
        print(f"[错误] profiles文件不存在: {profiles_path}")
        return ""

    with open(profiles_path, encoding="utf-8") as f:
        profiles = json.load(f)

    os.makedirs(output_dir, exist_ok=True)

    # 评级
    ratings = []
    for p in profiles:
        if not p.get("crawl_success"):
            continue
        r = analyze_profile(p)
        ratings.append(r)

    # 按分数排序
    ratings.sort(key=lambda x: x.score, reverse=True)

    recommended = [r for r in ratings if r.recommend]
    others = [r for r in ratings if not r.recommend]

    # ── 生成Markdown报告 ──────────────────────────────────────────────────────
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# 你的产品 KOL 筛选报告",
        f"",
        f"> 生成时间：{now}  ",
        f"> 产品：{product_name}  ",
        f"> CPM预算：¥{CPM_BUDGET}  ",
        f"> 分析达人：{len(ratings)} 人  |  建议合作：{len(recommended)} 人",
        f"",
        f"---",
        f"",
        f"## 一、建议合作达人（{len(recommended)} 人）",
        f"",
    ]

    if recommended:
        # 汇总表
        lines += [
            "| 排名 | 达人 | 等级 | 粉丝数 | 互动率 | 母婴内容 | 教育合作 | 报价 | 建议报价 | 估算CPM |",
            "| ---- | ---- | ---- | ------ | ------ | -------- | -------- | ---- | -------- | ------- |",
        ]
        for i, r in enumerate(recommended, 1):
            fans_str = f"{r.fans_count/10000:.1f}万" if r.fans_count >= 10000 else str(r.fans_count)
            price_str = f"¥{r.pgy_price}" if r.pgy_price else "待询"
            sugg_str = f"¥{r.suggested_price}" if r.suggested_price else "-"
            cpm_str = f"{r.estimated_cpm:.1f}" if r.estimated_cpm > 0 else "-"
            lines.append(
                f"| {i} | [{r.name}]({r.xhs_url}) | **{r.grade}** | {fans_str} | "
                f"{r.fans_engage_rate:.2f}% | {r.baby_content_ratio*100:.0f}% | "
                f"{r.edu_collab_count}篇 | {price_str} | {sugg_str} | {cpm_str} |"
            )

        lines += ["", "### 详细分析", ""]

        for i, r in enumerate(recommended, 1):
            fans_str = f"{r.fans_count/10000:.1f}万" if r.fans_count >= 10000 else str(r.fans_count)
            mode_tag = "🎯定向" if r.scout_mode == "targeted" else "🔀破圈"
            lines += [
                f"#### {i}. {r.name} — {r.grade}级（{r.score:.0f}分）{mode_tag}",
                f"",
                f"- **主页**：{r.xhs_url}",
                f"- **粉丝**：{fans_str}　**平均点赞**：{r.avg_likes:.0f}　**互动率**：{r.fans_engage_rate:.2f}%　**稳定性**：{r.interact_stability:.2f}",
                f"- **母婴内容占比**：{r.baby_content_ratio*100:.0f}%　**商业合作**：{r.collab_count}篇　**教育合作**：{r.edu_collab_count}篇",
            ]

            if r.edu_collab_examples:
                lines.append(f"- **教育合作笔记**：{' / '.join(r.edu_collab_examples)}")

            if r.pgy_price:
                lines.append(f"- **蒲公英报价**：¥{r.pgy_price}　**估算CPM**：{r.estimated_cpm:.1f}　**建议报价**：¥{r.suggested_price}")

            # 评论区数据
            lines += [
                f"- **评论质量**：{r.comment_quality_score:.1f}/10　"
                f"博主回复率：{r.avg_author_reply_rate*100:.0f}%　"
                f"家长关键词占比：{r.avg_parent_keyword_ratio*100:.0f}%　"
                f"疑似刷量：{r.comment_suspicious_count}篇",
            ]
            if r.comment_samples:
                lines.append(f"- **真实评论样本**：「{r.comment_samples[0]}」" +
                             (f" / 「{r.comment_samples[1]}」" if len(r.comment_samples) > 1 else ""))

            lines += [
                f"",
                f"**评级依据**：{r.reason}",
                f"",
                f"**建联话术**：",
                f"> {r.outreach_script}",
                f"",
                f"---",
                f"",
            ]
    else:
        lines += ["暂无达到推荐标准的达人。", ""]

    # 其他达人简表
    if others:
        lines += [
            f"## 二、其他候选达人（{len(others)} 人，暂不推荐）",
            "",
            "| 达人 | 等级 | 分数 | 粉丝数 | 互动率 | 不推荐原因 |",
            "| ---- | ---- | ---- | ------ | ------ | ---------- |",
        ]
        for r in others:
            fans_str = f"{r.fans_count/10000:.1f}万" if r.fans_count >= 10000 else str(r.fans_count)
            # 找出最低分项
            scores = {
                "互动率": r.score_engage,
                "受众匹配": r.score_audience,
                "教育经验": r.score_edu_exp,
                "稳定性": r.score_stability,
                "报价": r.score_price,
            }
            weakest = min(scores, key=lambda k: scores[k] / SCORING_WEIGHTS[
                {"互动率": "fans_engage_rate", "受众匹配": "audience_match",
                 "教育经验": "edu_collab_exp", "稳定性": "stability", "报价": "price_efficiency"}[k]
            ])
            lines.append(
                f"| [{r.name}]({r.xhs_url}) | {r.grade} | {r.score:.0f} | "
                f"{fans_str} | {r.fans_engage_rate:.2f}% | {weakest}偏弱 |"
            )

    lines += ["", "---", "", "*本报告由 KOL Scout 自动生成，数据来源于蒲公英后台及小红书公开主页。*"]

    report_md = "\n".join(lines)

    # 保存报告
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    md_path = os.path.join(output_dir, f"kol_report_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(report_md)

    # 同时保存结构化JSON
    json_path = os.path.join(output_dir, f"kol_ratings_{ts}.json")
    from dataclasses import asdict
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in ratings], f, ensure_ascii=False, indent=2)

    print(f"\n[报告] Markdown报告: {md_path}")
    print(f"[报告] JSON数据: {json_path}")
    print(f"\n{'='*60}")
    print(f"建议合作达人 {len(recommended)} 人：")
    for i, r in enumerate(recommended, 1):
        print(f"  {i}. {r.name} — {r.grade}级 {r.score:.0f}分  互动率{r.fans_engage_rate:.2f}%  教育合作{r.edu_collab_count}篇")
    print(f"{'='*60}")

    return md_path


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="tmp/profiles.json")
    p.add_argument("--output-dir", default="output")
    args = p.parse_args()
    generate_report(profiles_path=args.input, output_dir=args.output_dir)
