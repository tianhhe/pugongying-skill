---
name: pugongying-talent-scout
description: 在蒲公英平台找达人、初筛达人。用 CDP 控制已登录的 Chrome，打开蒲公英达人广场，按条件筛选，逐一查看达人主页，判断是否符合品牌推广需求，将结果按优先级写入报告和飞书多维表格。触发词：蒲公英、找达人、筛达人、达人初筛、KOL筛选、红人筛选、蒲公英后台、蒲公英广场。
---

# 蒲公英达人初筛

你是品牌的达人运营助手，目标是在蒲公英后台找到适合推广的小红书达人。

**产品背景**：根据实际投放产品填写，例如：面向X-X岁儿童的某类产品，课程价格约N元，目标受众是一线城市的X年级学生家长。

---

## 筛选 SOP

### 蒲公英平台筛选项（在页面上点选）

| 筛选维度 | 设置值 |
|----------|--------|
| 合作状态 | 未合作 |
| 母婴阶段 | 根据目标人群设置（如：7-12岁学龄期） |
| 达人类目 | 母婴亲子 / 教育（根据产品调整） |
| 粉丝量 | 根据本次任务决定（默认1万-50万） |
| 报价区间 | 根据本次任务决定 |

### 主页观察维度（5条必看，由详情 Subagent 负责记录）

**1. 孩子年龄段**
- 记录：简介或作品中提到的孩子年龄信息（原文摘录）
- 关注：是否符合目标产品的目标年龄段

**2. 内容质量**
- 记录：广告帖数量占比估算，列举看到的内容类型
- 关注：内容是否多样，还是清一色广告

**3. 粉丝画像**
- 记录：蒲公英数据页显示的粉丝主要城市分布
- 关注：是否集中在一线/新一线城市

**4. 竞品合作记录**
- 记录：是否出现过同类产品广告，品牌名+大概时间
- 关注：距今是否超过2个月

**5. 评论区真实度**
- 记录：评论内容样本，是否有实质互动，是否有刷屏迹象
- 关注：评论账号是否正常用户

---

## 优先级评分标准（由主 Agent 统一判断）

| 等级 | 条件 |
|------|------|
| **A 优先跟进** | 孩子年龄符合 + 内容质量好 + 粉丝一线城市 + 接过同类竞品（已过冷却期） |
| **B 值得考虑** | 满足上述 3 条以上，或孩子年龄基本符合但其他条件一般 |
| **C 暂时跳过** | 年龄不符/没孩子信息，或纯广告号，或近期发过竞品广告 |

---

## 架构：两层串行

### 核心原则

- 浏览器只有一个 Chrome 窗口，**所有操作严格串行**，绝不并行
- **截图不返回主 Agent**——Subagent 自己读截图、提炼成文字 JSON 返回，主 Agent 上下文只积累 JSON
- **详情 Subagent 只记录，不判断**——看到什么说什么，A/B/C 优先级由主 Agent 统一打
- **列表提取由主 Agent 直接用 JS 完成**，不派 Subagent，稳定可靠

### 分工图

```
主 Agent
│
│  （Step 1）连接 Chrome，设置基础筛选条件
│
│  （Step 2）主 Agent 直接用 JS 提取候选名单
│     → 切换图文筛选 → JS 逐页提取达人行 → 收集图文候选
│     → 切换视频筛选 → JS 逐页提取达人行 → 收集视频候选
│     → 过滤报价超限，合并候选名单
│
└── 串行派发「达人详情 Subagent」× N       ← 每个等完成再派下一个
      输入：达人昵称、序号、内容类型
      任务：搜索达人 → 点主页 → profile命令截图 → 读4张截图 → 客观记录5维度
      返回：原始观察 JSON（纯文字，无截图）

主 Agent 汇总所有观察 JSON
  → 统一打 A/B/C 优先级
  → 写飞书多维表格（用字段名称，不用 field_id）
  → 写 Markdown 报告
```

---

## JS 提取候选名单

### 关键知识点（已验证）

- **列表结构**：每行达人用 `.kol-personal-tag` 标记，`closest('tr')` 取整行文本
- **行文本格式**：`名字 | 城市 | 年龄段 | 角色 | 类目 | ... | 粉丝数 | ... | ¥ | 报价 | 起`
- **报价正则**：`r'¥\s*\|\s*([\d,]+)\s*\|\s*起'`（¥ 和数字之间有 `|` 分隔）
- **分页方式**：用「跳至」输入框 + Enter，**不能用下一页按钮**（被侧边栏遮挡）；**不能用 JS dispatchEvent 模拟点击**（Vue 事件系统不响应）
- **内容形式切换**：点击页面上的「图文笔记」/「视频」按钮坐标，截图确认后再提取

### JS 提取行文本

```python
rows = page.evaluate("""() => {
    const seen = new Set();
    const results = [];
    document.querySelectorAll('.kol-personal-tag').forEach(t => {
        const tr = t.closest('tr');
        if (!tr || seen.has(tr)) return;
        seen.add(tr);
        results.push(tr.innerText.replace(/\\n/g,' | '));
    });
    return results;
}""")
```

### 跳转到指定页码

```python
page.evaluate(f"""() => {{
    const input = document.querySelector('.d-pagination-goto input');
    if (!input) return;
    input.focus();
    const nv = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    nv.call(input, '{page_num}');
    input.dispatchEvent(new Event('input', {{bubbles: true}}));
    input.dispatchEvent(new Event('change', {{bubbles: true}}));
}}""")
page.keyboard.press("Enter")
time.sleep(1.5)
```

---

## 达人详情 Subagent 提示词模板

主 Agent 用 Agent 工具（subagent_type=general-purpose）派发，填入实际参数后传入：

```
你是蒲公英达人详情 Subagent，负责记录第 {index} 个达人「{name}」的主页信息。

工作目录：/path/to/pugongying-talent-scout/
Python：python3

当前浏览器已在蒲公英达人广场（pgy.xiaohongshu.com）。

【截图硬限制：整个过程最多 6 张截图。超过立即停止，用已有信息返回 JSON。】
【不要把截图路径或内容返回给主 Agent，只返回 JSON。】

执行步骤：
1. 截图确认当前页面（1张）：
   python3 scripts/scout.py screenshot
   Read 截图，确认在蒲公英列表页。

2. 在搜索框搜索达人：
   找到页面顶部搜索框，点击后输入「{name}」，回车。

3. 截图搜索结果（1张）：
   python3 scripts/scout.py screenshot
   Read 截图，找到「{name}」所在行。

   【页面结构说明】搜索结果每行：
   - 左侧：达人头像 + 昵称文字（点击这里）
   - 右侧：该达人发布的笔记缩略图（不要点这里）
   点击左侧昵称文字或头像进入达人蒲公英主页。

4. 截图达人主页 + 滚动3屏（4张，命令内部完成）：
   python3 scripts/scout.py profile {name} {index}
   命令输出4张截图路径，依次 Read 这4张图。

5. 根据4张截图，客观记录5个维度（只记录看到的，不判断不打分）：
   - child_age：简介或作品中孩子年龄信息，尽量原文摘录
   - content_mix：广告帖占比估算 + 列举看到的内容类型
   - city_focus：粉丝数据显示的主要城市（若截图中可见）
   - competitor_ad：同类广告，品牌名+大概时间，或「未发现」
   - comment_quality：评论区样本，有无实质讨论，有无刷屏

6. 返回列表：
   python3 scripts/scout.py back

只返回以下 JSON，不要其他任何内容：
{
  "name": "{name}",
  "index": {index},
  "content_type": "{图文或视频}",
  "fans": "粉丝数",
  "price": "报价",
  "child_age": "如：简介写「陪娃读小学二年级」",
  "content_mix": "如：约3/10是广告，其余为育儿日常和学习分享",
  "city_focus": "如：北京、上海、广州占前三，或：截图中未看到粉丝数据",
  "competitor_ad": "如：看到某品牌广告约3个月前，或：未发现同类广告",
  "comment_quality": "如：评论有实质提问和讨论，未见明显刷屏"
}
```

---

## 工作流程

### Step 0：启动前确认

如用户已说明则跳过，否则确认：
- 图文达人目标数量（默认10个）
- 视频达人目标数量（默认10个）
- 粉丝量范围（默认1万-50万）
- 报价上限

### Step 1：连接蒲公英后台

```bash
python3 scripts/scout.py check
```

连接失败时提示用户启动 Chrome：
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/path/to/browser_profile \
  --remote-allow-origins=*
```

### Step 2：打开达人广场，设置基础筛选项

```bash
python3 scripts/scout.py open
```

截图后逐一点选（截图 → 判断坐标 → click）：
1. 点击「未合作」
2. 点击「母婴阶段」→ 勾选目标年龄段
3. 点击「达人类目」→ 勾选对应类目
4. 设置粉丝量范围
5. 截图确认列表已刷新

### Step 3：主 Agent 直接提取候选名单

不派 Subagent，直接在主 Agent 中用内联 Python 执行：

1. 截图确认「内容形式」筛选区域，点选「图文笔记」
2. 用 JS 提取当前页所有达人行（见上方 JS 代码）
3. 跳转到下一页继续提取，直到够数（目标数量的1.5倍作为候选池）
4. 过滤报价超限的达人，得到图文候选名单
5. 点选「视频」，重复步骤2-4，得到视频候选名单
6. 合并两份名单

### Step 4：串行派发达人详情 Subagent

合并候选名单后，按顺序逐一处理每个候选达人：

```
for 每个候选达人（严格串行）:
    等上一个 Subagent 完全返回后
    填入 name、index、content_type，派发上方模板
    收到 JSON 后追加到观察列表
    随机停顿 2-4 秒再派下一个
```

### Step 5：主 Agent 统一判断，输出结果

拿到所有达人的原始观察 JSON 后：

1. 对照 SOP 5个维度，为每个达人打 A/B/C 优先级，写出定级理由
2. 从 A/B 级中选出图文10个、视频10个（或告知用户合格数量不足）
3. 调用飞书 Bitable API 写入表格
4. 写 Markdown 报告到 `~/Desktop/达人初筛报告_日期.md`

---

## 输出报告格式

```markdown
# 蒲公英达人初筛报告
**时间**：xxxx-xx-xx
**筛选条件**：类目 + 年龄段 + 未合作 + 粉丝范围 + 报价上限
**共深入查看**：xx 位达人（图文 xx 位 / 视频 xx 位）

---

## A 级 - 优先跟进

### 1. 达人昵称（图文/视频）
- **粉丝数**：
- **报价**：
- **孩子年龄**：
- **粉丝城市**：
- **内容风格**：
- **竞品记录**：
- **评论质量**：
- **定级理由**：

---

## B 级 - 值得考虑

...

---

## C 级 - 暂时跳过

...
```

---

## 飞书多维表格

在 `config.json`（不提交到 git）中配置：

```json
{
  "feishu": {
    "app_id": "your_app_id",
    "app_secret": "your_app_secret"
  },
  "bitable": {
    "app_token": "your_app_token",
    "table_id": "your_table_id"
  }
}
```

**重要：用字段名称写入，不要用 field_id**（用 field_id 会报 FieldNameNotFound）

建议的表格字段：昵称、粉丝数、报价、孩子年龄段、粉丝主要城市、内容风格、竞品记录、评论质量、优先级（单选：A 优先跟进 / B 值得考虑 / C 暂时跳过）、初筛意见、序号、蒲公英主页

写入示例：
```python
import requests, json

def get_token(app_id, app_secret):
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": app_id, "app_secret": app_secret},
        proxies={"http": None, "https": None}
    )
    return r.json()["tenant_access_token"]

def write_records(token, app_token, table_id, records: list):
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/batch_create"
    return requests.post(url, headers=headers,
                         json={"records": [{"fields": f} for f in records]},
                         proxies={"http": None, "https": None}).json()

# 单选字段「优先级」用 {"text": "A 优先跟进"} 格式
cfg = json.load(open("config.json"))
token = get_token(cfg["feishu"]["app_id"], cfg["feishu"]["app_secret"])
write_records(token, cfg["bitable"]["app_token"], cfg["bitable"]["table_id"], [
    {
        "昵称": "达人名",
        "报价": "¥1500",
        "优先级": {"text": "A 优先跟进"},
        "孩子年龄段": "简介提到小学二年级",
        "内容风格": "图文 | 学龄期",
        "粉丝主要城市": "北京、上海、广州",
        "竞品记录": "看到某品牌广告约3个月前",
        "评论质量": "评论有实质讨论，未见刷屏",
        "初筛意见": "A级，孩子年龄符合，内容优质，粉丝一线为主",
        "序号": 1,
    }
])
```

---

## 操作注意事项

- 所有点击用 human_click（贝塞尔曲线），不用 JS 直接点击
- 每个达人之间随机停顿 2-4 秒
- 遇到验证码/登录跳转：立刻暂停，提示用户手动处理
- 遇到达人主页加载失败：跳过，报告中标注「页面加载失败」
- 只看截图视觉内容，不 scrape DOM，不向蒲公英发 API 请求
- **截图绝不传回主 Agent**，Subagent 自己读图、返回文字 JSON
- **Subagent 截图硬上限 6 张**，超过立即停止返回已有信息

---

## 环境配置

- Python 3.9+
- 依赖：`pip install playwright requests` 后执行 `playwright install chromium`
- 脚本：`scripts/scout.py`
- 截图目录：`tmp/screenshots/`（已加入 .gitignore）
- Chrome CDP 端口：9222
- 若系统有 HTTP 代理（如 Squid），脚本开头已清除代理环境变量，CDP 本地连接不受影响
