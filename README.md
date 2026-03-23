# pugongying-skill

用 Claude Code + Playwright CDP 在蒲公英达人广场自动筛选 KOL，深度分析小红书主页和评论区，输出评级报告和建联话术。

---

## 能做什么

- **蒲公英初筛**：自动在蒲公英后台按类目/粉丝/互动筛选候选达人，支持双轮模式（定向+破圈）
- **小红书主页分析**：逐一访问每个博主主页，抓取笔记数据、识别教育类合作历史、分析受众匹配度
- **评论区分析**：抽样高赞笔记，判断评论真实性、博主回复率、目标受众关键词占比，识别疑似刷量
- **智能评级**：按受众匹配(30) + 教育合作经验(25) + 报价性价比(20) + 互动率(15) + 评论质量(10) 综合打分
- **生成报告**：输出带评级、建联话术的 Markdown 报告

---

## 技术实现

- **CDP + Playwright**：复用已登录的 Chrome，无需额外登录，低风控
- **模拟真人节奏**：贝塞尔曲线鼠标移动、不均匀滚动、随机停顿，每10个博主自动大休息
- **无需爬虫**：不依赖 MediaCrawler 或第三方爬虫，直接读取页面数据

---

## 安装

```bash
# 1. 把 pugongying-skill 文件夹放到 Claude skills 目录
cp -r pugongying-skill ~/.claude/skills/

# 2. 安装依赖
python3 ~/.claude/skills/pugongying-skill/scripts/setup.py install

# 3. 配置你的产品信息
vim ~/.claude/skills/pugongying-skill/scripts/config.py
```

详见 [安装说明.md](安装说明.md)

---

## 使用

在 Claude Code 中输入：

```
/pugongying-skill
```

或直接命令行：

```bash
cd ~/.claude/skills/pugongying-skill
python3 scripts/kol_scout.py run         # 完整流程
python3 scripts/kol_scout.py scout       # 只跑蒲公英初筛
python3 scripts/kol_scout.py analyze     # 只跑小红书分析
python3 scripts/kol_scout.py report      # 只生成报告
```

---

## 评分权重

| 维度 | 分值 | 说明 |
|------|------|------|
| 受众匹配度 | 30 | 内容占比 + 账号标签 + 简介信号 |
| 教育/品类合作经验 | 25 | 有过相关品类合作的博主更可信 |
| 报价性价比 | 20 | 基于 CPM 预算评估性价比 |
| 互动率 | 15 | 粉丝活跃度验证 |
| 评论区质量 | 5 | 真实互动 + 博主回复习惯 |
| 稳定性 | 5 | 互动数据一致性 |

---

## License

MIT
