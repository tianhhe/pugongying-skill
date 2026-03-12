# pugongying-copilot

用 Claude Code + Playwright CDP 控制已登录的 Chrome，在蒲公英达人广场自动筛选、逐一查看达人主页，输出初筛报告和飞书多维表格。

---

## 能做什么

- 在蒲公英后台按条件（母婴阶段、类目、粉丝量、报价）筛选达人
- 用 JS 批量提取列表数据，自动翻页，过滤超预算达人
- 逐一进入每个达人主页，截图并记录5个维度：
  - 孩子年龄段
  - 内容质量（广告占比）
  - 粉丝城市分布
  - 竞品合作记录
  - 评论区真实度
- 按 A/B/C 优先级输出初筛报告（Markdown）
- 写入飞书多维表格

---

## 架构

两层串行，主 Agent 不处理截图：

```
主 Agent
├── Step 1  连接 Chrome（CDP 9222），设置筛选条件
├── Step 2  JS 直接提取候选名单（图文 + 视频各约20个）
└── Step 3  串行派发达人详情 Subagent × N
            每个 Subagent：搜索达人 → 进主页 → 截图4张 →
            自己读图 → 返回文字 JSON（截图不传回主 Agent）

主 Agent 收到所有 JSON → 打优先级 → 写飞书 → 写报告
```

核心设计原则：
- **截图上下文隔离**：Subagent 自己读截图，只返回文字 JSON，主 Agent 上下文不被截图污染
- **严格串行**：浏览器只有一个窗口，所有操作排队执行
- **记录与判断分离**：Subagent 只记录事实，优先级由主 Agent 统一打

---

## 文件结构

```
.
├── SKILL.md              # Claude Code skill 配置，包含完整 SOP 和 Subagent 提示词
├── README.md
├── config.json.example   # 飞书/表格配置示例（复制为 config.json 后填入真实值）
└── scripts/
    └── scout.py          # Playwright CDP 工具脚本
```

`scout.py` 提供以下命令：

| 命令 | 说明 |
|------|------|
| `check` | 检查 CDP 连接，截图当前页面 |
| `screenshot [name]` | 截图当前页面 |
| `open` | 导航到蒲公英达人广场 |
| `click X Y` | 人类模拟点击（贝塞尔曲线） |
| `scroll [down\|up] [距离]` | 模拟滚动 |
| `profile 昵称 序号` | 截图达人主页（简介 + 滚动3屏作品，共4张） |
| `back` | 返回上一页 |

---

## 环境要求

- macOS，Python 3.9+
- `pip install playwright requests`，然后 `playwright install chromium`
- Chrome 以 CDP 模式启动（见下方）
- 飞书自建应用（用于写入多维表格）

启动 Chrome：
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir=/path/to/browser_profile \
  --remote-allow-origins=*
```

---

## 配置

复制 `config.json.example` 为 `config.json`，填入你的飞书 App 凭据和表格信息：

```json
{
  "feishu": {
    "app_id": "cli_xxx",
    "app_secret": "xxx"
  },
  "bitable": {
    "app_token": "xxx",
    "table_id": "tblxxx"
  }
}
```

`config.json` 已加入 `.gitignore`，不会被提交。

---

## 使用方式

在 Claude Code 中说：

> 去蒲公英找10个图文达人、10个视频达人，粉丝1-50万，报价3000以内

Claude 会自动执行完整 SOP，过程无需干预，最终输出：
- `~/Desktop/达人初筛报告_日期.md`
- 飞书多维表格（A/B/C 分级）

---

## 已知注意事项

- 蒲公英列表分页（约400页），用「跳至」输入框翻页；JS dispatchEvent 和下一页按钮均无效
- 报价在 DOM 中格式为 `¥ | 3,000 | 起`，提取用正则 `¥\s*\|\s*([\d,]+)\s*\|\s*起`
- 飞书 Bitable API 写入必须用字段名称，不能用 field_id
- Subagent 截图上限6张，超限立即返回已有信息，避免触发图片尺寸限制错误
