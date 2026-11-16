# 舞萌报卡 (astrbot_plugin_maimai_card_report) 项目备忘录

## 重要规则
- **每次对话取得重要进展后，必须更新本文件**
- **编辑文件反复失败时**：大概率是 VS Code 文件锁/缓存出问题，立即停止编辑，让用户关掉 VS Code 重开，然后再试
- **严禁使用 `replace_all` 工具参数**：会导致 VS Code 卡死/编辑失败。始终使用精确的 `old_string` 匹配单次替换，不做全局替换
- **编辑超长 JS/字符串拼接时**：不要用一个巨大 old_string 覆盖整段，拆成多个小 edit，每个只改单行或相邻两三行；old_string 带足上下文保证唯一；改完用 Grep 验证残留，再编译验证

## 环境与路径

### 插件模板
- 模板仓库：`https://github.com/Soulter/helloworld`
- 本地模板路径：`e:\Program\helloworld\`

### AstrBot 开发文档
- 文档仓库：`https://github.com/AstrBotDevs/AstrBot`（sparse checkout，仅 `docs/zh/dev`）
- 本地文档路径：`e:\Program\AstrBot\docs\zh\dev\`
- 核心文档（已通读学习）：
  - `star/plugin-new.md` — 新插件开发指南（从这里开始）
  - `star/plugin.md` — 旧版指南（API 细节更全，可参考）
  - `star/plugin-publish.md` — 发布到插件市场
  - `star/guides/simple.md` — 最小实例
  - `star/guides/plugin-config.md` — 插件配置 `_conf_schema.json`
  - `star/guides/send-message.md` — 消息发送（被动/主动/富媒体/按钮）
  - `star/guides/listen-message-event.md` — 消息事件监听（指令/过滤器/钩子）
  - `star/guides/storage.md` — KV 存储 + 大文件目录规范
  - `star/guides/session-control.md` — 会话控制（成语接龙式多轮对话）
  - `star/guides/plugin-pages.md` — 插件可视化视图（views/ + Web API）
  - `star/guides/other.md` — 平台实例、OneBot API、获取插件/平台列表
  - `star/guides/ai/tools.md` — 定义/注册 LLM Tool
  - `star/guides/ai/agent.md` — 调用/构建 Agent

### AstrBot 实例
- 实例路径：`C:\Users\Tool-yang\.astrbot_launcher\instances\8066b83f-1fe3-4a8c-a749-9913203b1f38\`
- 插件调试位置：实例内 `data/plugins/<插件目录名>/`（运行时注入机制，改代码后在 WebUI「插件」页点刷新图标重载）

## 项目结构（舞萌报卡）

- `e:\Program\astrbot_plugin_maimai_card_report\main.py` — 插件主文件（必须命名为 main.py）
- `e:\Program\astrbot_plugin_maimai_card_report\metadata.yaml` — 插件元数据
- `e:\Program\astrbot_plugin_maimai_card_report\_conf_schema.json` — 全局默认配置 schema
- `e:\Program\astrbot_plugin_maimai_card_report\astrbot_compat.py` — AstrBot 兼容层
- `e:\Program\astrbot_plugin_maimai_card_report\config.py` — 常量 / 默认值 / 数据路径
- `e:\Program\astrbot_plugin_maimai_card_report\utils.py` — 文本归一化 / 中文数字 / 时间工具
- `e:\Program\astrbot_plugin_maimai_card_report\backend\models.py` — 数据模型（dataclass）
- `e:\Program\astrbot_plugin_maimai_card_report\backend\store.py` — JSON 持久化（线程安全，含级联删除 / 清零）
- `e:\Program\astrbot_plugin_maimai_card_report\backend\parser.py` — 报卡 / 查询解析（纯函数）
- `e:\Program\astrbot_plugin_maimai_card_report\backend\service.py` — 业务逻辑（机厅匹配 / 报卡 / 查询 / 异常 / 黑名单 / help 指令）
- `e:\Program\astrbot_plugin_maimai_card_report\backend\validation.py` — 机厅 / 机台配置校验
- `e:\Program\astrbot_plugin_maimai_card_report\mixins\event_handlers.py` — 群消息事件入口（路由到 service）
- `e:\Program\astrbot_plugin_maimai_card_report\mixins\web_api.py` — 后端 API（供 WebUI 调用，仅 GET / POST）
- `e:\Program\astrbot_plugin_maimai_card_report\pages\dashboard\index.html` — 控制台（首页看板 / 机厅管理 / 设置与调试 三合一页签）
- `e:\Program\astrbot_plugin_maimai_card_report\.astrbot-plugin\i18n\*.json` — 页面侧边栏标题 / 描述国际化
- `e:\Program\astrbot_plugin_maimai_card_report\main.py` — 主入口（Mixin 装配 + 30 秒定时清零任务）
- `e:\Program\astrbot_plugin_maimai_card_report\tests\` — 单元测试（parser / validation / store / service）
- `e:\Program\astrbot_plugin_maimai_card_report\reference\` — 参考项目（astrbot_plugin_meme_manager）
- `e:\Program\astrbot_plugin_maimai_card_report\history.md` — 本备忘录（开发记录）

## 插件开发核心知识（学习笔记）

### 1. 最小结构
```python
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register
from astrbot.api import logger

@register("helloworld", "YourName", "描述", "1.0.0")
class MyPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)

    @filter.command("helloworld")
    async def helloworld(self, event: AstrMessageEvent):
        """handler 描述，会被解析展示，建议填写"""
        yield event.plain_result("Hello!")

    async def terminate(self):
        """插件卸载/停用时调用"""
```
- 插件类继承 `Star`，文件名必须为 `main.py`
- `Context` 用于与 AstrBot Core 交互
- handler 前两个参数必须是 `self` 和 `event`
- 必须用 `from astrbot.api import logger`，不要用 `logging`

### 2. 消息事件监听
- `@filter.command("名")` — 指令（不能带空格，可用 `alias={"别名"}`）
- `@filter.command("add")` + 参数注解 `(self, event, a: int, b: int)` — 带参指令自动解析
- `@filter.command_group("math")` + `@math.command("add")` / `@math.group("calc")` — 指令组可无限嵌套
- `@filter.event_message_type(filter.EventMessageType.ALL / PRIVATE_MESSAGE / GROUP_MESSAGE)`
- `@filter.platform_adapter_type(filter.PlatformAdapterType.AIOCQHTTP | ...)`
- `@filter.permission_type(filter.PermissionType.ADMIN)` — 管理员指令
- 多过滤器为 AND 逻辑；可加 `priority=1`
- `event.stop_event()` — 停止事件传播

### 3. 事件钩子（不能与上面的过滤器混用，用 `event.send()` 而非 yield）
- `@filter.on_astrbot_loaded()` / `on_llm_request(req)` / `on_llm_response(resp)` / `on_decorating_result()` / `after_message_sent()`
- 追加动态提示词优先用 `req.extra_user_content_parts.append(TextPart(...))`，不要频繁改 `system_prompt`（破坏缓存）

### 4. 发送消息
- 被动：`yield event.plain_result("文本")` / `event.image_result("路径或 http url")` / `event.chain_result(chain)`
- 主动：`await self.context.send_message(event.unified_msg_origin, message_chain)`，可把 `unified_msg_origin` 存起来定时发送
- 富媒体：`import astrbot.api.message_components as Comp`，用 `Comp.Plain/At/Image.fromURL/Image.fromFileSystem/File/Record/Video/Face/Node/ActionRow/Button`
- 交互按钮：`@filter.button_action("插件名:按钮id")` + `event.get_button_interaction()`

### 5. 插件配置
- 插件目录放 `_conf_schema.json`，AstrBot 据此生成 WebUI 表单
- `__init__(self, context, config: AstrBotConfig)` 接收配置，`self.config["key"]` 读取，`self.config.save_config()` 保存
- 配置类型：`string/text/int/float/bool/object/list/dict/template_list/file`
- 特殊：`secret:true`(密码)、`options/labels/subtitles`(下拉)、`slider`(滑块)、`render_type:"checkbox"`、`editor_mode`、`_special`(provider/persona/knowledgebase/sender_id/umo 选择器)

### 6. 存储
- KV：`await self.put_kv_data("k", v)` / `await self.get_kv_data("k", default)` / `await self.delete_kv_data("k")`（需 >= 4.9.2）
- 大文件：存 `data/plugin_data/{plugin_name}/`，用 `from astrbot.api.util import get_astrbot_data_path`

### 7. 会话控制（多轮对话）
- `from astrbot.api.util import session_waiter, SessionController`
- `@session_waiter(timeout=60)` 装饰内部 waiter；`controller.keep()` / `controller.stop()`；超时抛 `TimeoutError`

### 8. LLM Tool / Agent
- 定义：`@dataclass class XTool(FunctionTool[AstrAgentContext])`，字段 name/description/parameters，实现 `async def call(...)`
- 注册：`self.context.add_llm_tools(XTool())`（>= 4.5.1）
- 装饰器方式：`@filter.llm_tool(name="...")`，docstring 必须含 `Args:` 段，格式 `参数名(类型): 描述`
- 调用现有会话 Agent：`await self.context.agent.run_turn(umo=..., input_message=[PlainInput(text=...)])`
- 自定义 Agent：`await self.context.tool_loop_agent(event=..., chat_provider_id=..., prompt=..., tools=ToolSet([...]), max_steps=30)`

### 9. 可视化视图（可选）
- 插件目录 `views/<view_name>/index.html`，前端经 `window.AstrBotPluginView` bridge 通信
- 后端 `self.context.register_web_api("/{PLUGIN_NAME}/xxx", handler, ["GET"], "desc")`
- 用 `from astrbot.api.web import request, json_response, error_response, file_response, stream_response`

## 开发原则（官方要求）
1. 功能需经过测试；2. 良好注释；3. 持久化数据存 `data` 目录而非插件目录；4. 良好错误处理；5. 提交前用 ruff 格式化；6. **不要用 `requests`，用 `aiohttp`/`httpx`**；7. 功能扩增优先提交 PR；8. 借鉴需在 README 说明来源；9. 遵守开源协议

## 发布规范（metadata.yaml）
- `name`：英文唯一，推荐 `astrbot_plugin_` 前缀，全小写无空格
- `display_name`/`desc`/`short_desc`/`version`/`author`/`repo` 必填或推荐
- 可选：`astrbot_version`(PEP 440，不加 v)、`support_platforms`(list)、`social_link`、`tags`
- 插件压缩包 zip 不得超过 16MB

## 打包发布（zip）详细步骤

> 目标：把插件目录打包成可在 AstrBot WebUI 面板上传安装的 zip，供其他 AI Agent / 运维人员无脑执行。
> 采用**白名单复制**策略：只复制运行必需文件，天然排除开发/参考/测试/缓存/运行时数据文件。

### 打包前必须确认的关键事实（已核实源码）
1. **zip 顶层文件夹名 = `metadata.yaml` 的 `name` 字段**（本项目为 `maimai_card_report`）。
   - 依据：`astrbot/core/star/star_manager.py` 的 `_get_plugin_dir_name_from_metadata()` 用 `metadata.name` 归一化后作为插件目录名。
   - 安装流程：上传 zip → `_resolve_archive_root_dir()` 定位顶层目录 → 找到其中的 `metadata.yaml` → 读 `name` → 拷贝到 `data/plugins/<name>/`。
2. **zip 内根目录必须直接包含 `main.py` 与 `metadata.yaml`**（可带一层顶层文件夹，但不能再嵌套更深层）。
3. **无第三方依赖**：核心代码只依赖标准库 + AstrBot 内置模块（`astrbot.api.*`、`quart`），因此**不需要 requirements.txt**。
4. **大小限制 16MB**：本插件约 53KB，远低于上限。
5. 新增 Web API 时注意仅支持 GET/POST（前端桥接限制），与打包无直接关系，但改代码后需重新打包。

### 白名单清单（改动插件结构时必须同步维护）
根目录文件（逐个列出，缺一不可）：
- `main.py`
- `metadata.yaml`
- `_conf_schema.json`
- `astrbot_compat.py`
- `config.py`
- `utils.py`
- `log.py`
- `__init__.py`
- `README.md`（面板展示说明，可选保留）
- `LICENSE`（开源协议要求，保留）

目录（递归复制，内部自动清除 `__pycache__`/`*.pyc`）：
- `backend/`（models.py / parser.py / service.py / store.py / validation.py / __init__.py）
- `mixins/`（event_handlers.py / web_api.py / __init__.py）
- `pages/`（dashboard/index.html）
- `.astrbot-plugin/`（i18n/zh-CN.json / i18n/en-US.json，页面侧边栏标题国际化）

**排除**（白名单策略下天然不会进入，但改动清单时警惕）：`reference/`、`tests/`、`history.md`、`__pycache__/`、`*.pyc`、`.gitignore`、`data/`（本地回退产生的运行时数据）、任何临时文件。

### 打包脚本（PowerShell，可整体粘贴执行）
```powershell
$ErrorActionPreference = 'Stop'
$src  = 'e:\Program\astrbot_plugin_maimai_card_report'
$tmp  = 'e:\Program\_maimai_pack_tmp'
$zip  = 'e:\Program\maimai_card_report.zip'
$top  = 'maimai_card_report'   # 必须与 metadata.yaml 的 name 字段一致

# 1) 清理旧产物
if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
if (Test-Path $zip) { Remove-Item -Force $zip }

# 2) 建 staging 目录（即 zip 内的顶层文件夹）
$stage = Join-Path $tmp $top
New-Item -ItemType Directory -Force -Path $stage | Out-Null

# 3) 复制根目录核心文件（白名单，逐个列出）
$rootFiles = @('main.py','metadata.yaml','_conf_schema.json','astrbot_compat.py','config.py','utils.py','log.py','__init__.py','README.md','LICENSE')
foreach ($f in $rootFiles) {
    $s = Join-Path $src $f
    if (Test-Path $s) { Copy-Item $s (Join-Path $stage $f) }
}

# 4) 复制运行所需目录（逐条写，避免用含逗号的数组被终端拆坏）
Copy-Item (Join-Path $src 'backend')          (Join-Path $stage 'backend')          -Recurse
Copy-Item (Join-Path $src 'mixins')           (Join-Path $stage 'mixins')           -Recurse
Copy-Item (Join-Path $src 'pages')            (Join-Path $stage 'pages')            -Recurse
Copy-Item (Join-Path $src '.astrbot-plugin')  (Join-Path $stage '.astrbot-plugin')  -Recurse

# 5) 清除 Python 缓存
Get-ChildItem -Path $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem -Path $stage -Recurse -File -Filter '*.pyc' | Remove-Item -Force

# 6) 压缩（-Path 传目录本身 => zip 内保留顶层文件夹）
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal

# 7) 清理临时目录
Remove-Item -Recurse -Force $tmp

# 8) 校验：列出 zip 内容 + 大小
Write-Output '=== ZIP 内容 ==='
tar -tf $zip
Get-Item $zip | Select-Object FullName, @{N='SizeKB';E={[math]::Round($_.Length/1KB,1)}} | Format-List
```

### 打包后校验清单（必须逐项核对，用 `tar -tf $zip` 输出对照）
- [ ] 顶层只有一个文件夹 `maimai_card_report/`（无更深嵌套、根目录无裸文件）
- [ ] 根目录含 `main.py`、`metadata.yaml`、`_conf_schema.json`、`astrbot_compat.py`、`config.py`、`utils.py`、`log.py`、`__init__.py`
- [ ] 含 `backend/`（models.py、parser.py、service.py、store.py、validation.py、__init__.py）
- [ ] 含 `mixins/`（event_handlers.py、web_api.py、__init__.py）
- [ ] 含 `pages/`（dashboard/index.html）
- [ ] 含 `.astrbot-plugin/i18n/`（zh-CN.json、en-US.json）
- [ ] **不含** `reference`、`tests`、`history.md`、`__pycache__`、`.pyc`、`.gitignore`、`data`
- [ ] 大小 < 16MB（当前约 53KB）

### 常见坑（务必遵守，否则会导致面板安装失败）
1. **不要**用 `Compress-Archive -Path "$src\*"`：会把文件平铺到 zip 根（无顶层文件夹）且混入 reference/tests 等。必须走 staging 目录白名单复制。
2. **不要**在 zip 内套两层目录（如 `astrbot_plugin_maimai_card_report/maimai_card_report/`）。
3. **顶层文件夹名必须与 metadata name 一致**：若未来把 `name` 改为 `astrbot_plugin_maimai_card_report`，脚本里 `$top` 要同步改。
4. 未来新增运行必需文件/目录时，必须同步加入白名单清单，否则会漏打包。
5. 打包前建议先跑 `python -m compileall`（或 `python -m pytest tests`）确认无语法/逻辑错误。

## 主人信息
- QQ：806845531
- 用户名：Tool-yang
- 当前日期：2026-11-15

## 参考项目学习笔记（astrbot_plugin_meme_manager）

### 项目结构
```
reference/astrbot_plugin_meme_manager/
├── main.py              # Star 子类，多 Mixin 组合（WebAPIMixin/CommandMixin/EventHandlerMixin）
├── metadata.yaml        # name/display_name/desc/version/author/repo/astrbot_version/tags
├── _conf_schema.json    # 全局配置 schema（object 类型，内含数组/对象）
├── config.py            # 配置常量 + get_plugin_data_dir()（优先 get_astrbot_plugin_data_path()，回退本地 data）
├── astrbot_compat.py    # 延迟导入可选依赖 + 版本差异适配 + 回退
├── utils.py             # 工具函数
├── mixins/web_api.py    # _register_webui_api() 统一注册路由，前缀 /<plugin_name>/<route>
├── mixins/command.py    # 指令处理
├── mixins/event_handler.py # 事件钩子（on_llm_request 等）
├── pages/               # WebUI 页面（每个子目录一个页面，含 index.html）
└── tests/               # pytest 测试
```

### 可复用点
- **分层架构**：配置封装 / AstrBot 兼容层 / 工具函数 / 业务模块 / 后端 API / 前端页面分离
- **Web API 注册模式**：统一 `_register_webui_api(route, handler, methods)` 辅助方法，自动打日志
- **数据目录获取**：`get_plugin_data_dir()` 优先 AstrBot 官方 API，失败回退本地 `data/plugin_data/<name>`
- **Mixin 组合**：主类只做装配，指令 / 事件 / WebAPI 各自成模块
- **metadata.yaml**：字段规范与官方要求一致

### 已确认的 AstrBot 4.29.3 公开 API（全部核实，无臆造）
- 导入入口：`astrbot.api`、`astrbot.api.star`、`astrbot.api.event`、`astrbot.api.event.filter`、`astrbot.api.web`、`astrbot.api.provider`、`astrbot.api.util`、`astrbot.api.all`
- `Star` 基类、`Context`、`@register(name, author, desc, version)` 从 `astrbot.api.star` 导入
- `AstrMessageEvent`、`MessageEventResult`、`MessageChain` 从 `astrbot.api.event` 导入
- filter 装饰器全集（`astrbot.api.event.filter`）：command / command_group / event_message_type / regex / permission_type / platform_adapter_type / on_astrbot_loaded / on_llm_request / on_llm_response / on_agent_begin / on_agent_done / on_decorating_result / after_message_sent / on_waiting_llm_request / on_plugin_loaded / on_plugin_unloaded / on_plugin_error / on_platform_loaded / on_using_llm_tool / on_llm_tool_respond / custom_filter
- `Context` 方法：`llm_generate()` / `tool_loop_agent()` / `get_using_provider_async()` / `send_message()` / `register_web_api()` / `get_config()`
- `AstrMessageEvent`：`unified_msg_origin` / `get_group_id()` / `get_sender_id()` / `get_message_str()` / `stop_event()` / `should_call_llm()` / `make_result()` / `plain_result()` / `image_result()` / `chain_result()`
- `MessageChain` 链式：`message()` / `at()` / `url_image()` / `file_image()` / `base64_image()`
- Web API：`from astrbot.api.web import request, json_response, error_response, file_response, stream_response`；`context.register_web_api("/{PLUGIN_NAME}/xxx", handler, ["GET"], "desc")`
- Web API 返回值自动转换：dict/list → JSONResponse；Quart Response → 自适应；`(content, status, headers)` 元组格式
- 插件数据目录：`get_astrbot_plugin_data_path()` 返回 `{ROOT}/data/plugin_data`，插件数据按插件名子目录隔离（回退本地 data 目录）
- WebUI 页面自动发现：优先 `views/` 目录，其次 `pages/` 目录；每个子目录一个页面，需含 `index.html`；前端注入桥接脚本 `/api/plugin/page/bridge-sdk.js`
- **页面排序与默认打开页关键坑（务必遵守）**：`discover_plugin_pages()`（`astrbot/dashboard/services/plugin_page_service.py`）用 `sorted(..., key=lambda item: item.name.lower())` **按目录名字典序**排列页面，前端侧边栏与「点击插件默认打开」都用 `pages[0]`（第一个）。因此 `arcades` 会排在 `dashboard` 之前导致默认打开「机厅管理」而非首页。修复方法：页面目录名加数字前缀控制顺序（如 `1-dashboard` / `2-arcades` / `3-settings`），并用 `.astrbot-plugin/i18n/<locale>.json` 的 `views.<view_name>.title` 映射侧边栏显示名（`view_name` 必须与目录名完全一致），避免前缀显示到 UI。本项目已采用此方案。
- 前端桥接：`window.AstrBotPluginView`（别名 `AstrBotPluginPage`）提供 `ready()` / `getContext()` / `getLocale()` / `t()` / `onContext()` / `apiGet()` / `apiPost()` / `upload()` / `download()` / `subscribeSSE()` / `unsubscribeSSE()`
- **前端桥接关键坑（务必遵守）**：AstrBot 会自动把 bridge-sdk.js 注入到 HTML 的 `</body>` **之前**（见 `astrbot/dashboard/services/plugin_page_service.py` 的 `process_plugin_page_html()`）。因此**内联 `<script>` 同步访问 `window.AstrBotPluginView` 时会得到 undefined**，报 `Cannot read properties of undefined (reading 'apiGet')`。修复方法（官方文档 plugin-pages.md 明确要求）：在页面 `<head>` 里显式引入 `<script src="/api/plugin/page/bridge-sdk.js"></script>`（AstrBot 会用它重写 URL 加 token，且不会重复注入）；或者改用外部 `type="module"` 脚本 + `await bridge.ready()`。注意 `apiGet`/`apiPost` 不依赖 `ready()`（bridge-sdk.js 内直接 postMessage），但 `ready()` 用于获取上下文/主题，初始化前建议 `await bridge.ready()`。本项目三个页面已采用显式引入方案修复。
- **前端桥接数据解包关键坑（务必遵守）**：Dashboard 前端 SDK（`dashboard/src/views/PluginViewPage.vue::handleBridgeRequest`）转发插件 API 响应时执行 `sendBridgeResponse(requestId, true, response.data?.data ?? response.data)`，即**只要后端响应 JSON 含 `data` 字段就无条件解包为 data 字段的值**；失败（HTTP 非 2xx）则 reject，错误信息取后端 JSON 的 `message` 字段。因此后端返回 `{"ok": true, "data": 业务数据}` 时，前端 `apiGet/apiPost` resolve 的是**业务数据本身**（不含 `ok` 字段），而不是 `{ok, data}` 包装。前端不能再写 `if (!r.ok)`，否则 `r.ok` 恒为 undefined 被误判为失败（表现就是页面顶部只显示「加载失败」且无原因）。本项目修复：前端 `get/post` 封装统一做兼容转换（`r && typeof r === 'object' && r.ok === false ? r : { ok: true, data: r }`），后端 `{"ok", "data"/"message"}` 结构保持不变。
- LLM：`LLMResponse`（`role` / `completion_text` 字段）；`Provider` 基类 `meta()` / `text_chat()`；`ProviderRequest`
- 事件钩子 `on_llm_request(req)` 用 `req.extra_user_content_parts.append(TextPart(...))` 追加动态提示词，不频繁改 system_prompt

## 舞萌报卡架构设计

### 数据模型（backend/models.py，dataclass + JSON 序列化）
- `Arcade`：机厅（id/name/aliases/group_ids/allow_cross_group/open_time/close_time/timezone/open&close message 配置/expire_hours/expire_scope/normal_count_min/max/error_message_template/machines）
- `Machine`：机台（id/name/aliases/is_default/position_mode/position_aliases/position_count）
- `CardRecord`：排队记录（arcade_id/machine_id/position_key/count/last_update_*）
- `AbnormalUser`：异常用户（arcade_id/qq/machine_id/abnormal_count/status=warning|ignored/时间戳/最近原始消息）

### 解析设计（backend/parser.py，纯函数）
- 文本归一化 `normalize_text()`：去首尾空格 + 折叠空白 + NFKC 全角转半角 + 小写 + 中文数字转阿拉伯数字
- 机厅解析：先匹配机厅别名（最长优先），无则按群号绑定确定机厅
- 机台解析：匹配机台别名（最长优先），无则默认机台
- 方位解析：匹配方位别名 key 与 label（如 z/左、y/右、n/内、w/外），支持 + 累加、k/卡/人 单位
- 查询解析：后缀 jk / 几卡 / 几k / ?卡 / ?k
- 数值校验：负数 / 非整数 / 越界 → 异常

## 变更记录

### 2026-11-15 - 初始化
- 拉取插件模板 helloworld 到 `e:\Program\helloworld\`
- 拉取 AstrBot 开发文档（sparse checkout）到 `e:\Program\AstrBot\docs\zh\dev\`
- 通读并学习全部核心开发文档，建立本备忘录
- 状态：**已就绪，等待插件开发需求**

### 2026-11-15 - 参考项目学习 + API 确认 + 目录重命名
- 克隆参考项目 anka-afk/astrbot_plugin_meme_manager 到 `reference/` 目录并通读学习
- 逐一核实 AstrBot 4.29.3 运行实例中的全部核心公开 API（filter 装饰器全集、Web API、Context、AstrMessageEvent、MessageChain、数据目录、WebUI 页面发现、前端桥接、LLM、Provider）
- 将插件目录重命名为 `e:\Program\astrbot_plugin_maimai_card_report`（robocopy 绕过 VS Code 文件锁），清理旧目录
- 状态：**接口确认完成，开始插件实现**

### 2026-11-15 - 后端全栈实现
- 完成兼容层 astrbot_compat.py、config.py、utils.py（文本归一化 / 中文数字 / 时间工具）
- 完成 backend 层：models.py（Arcade/Machine/CardRecord/AbnormalUser）、store.py（线程安全 JSON 持久化，含级联删除 / 清零）、parser.py（机厅/机台/方位匹配、报卡/查询解析、正负号与累加识别、异常尝试判定）、service.py（报卡/查询/超时清零/异常过滤/黑名单/开门闭店语）、validation.py（机厅/机台配置校验）
- 完成 mixins 层：event_handlers.py（群消息路由）、web_api.py（全部数据与操作接口）
- 完成 main.py（Mixin 装配 + 30 秒定时清零任务）、metadata.yaml、_conf_schema.json
- 确认 Web API 仅支持 GET/POST：所有 DELETE 路由改为 POST，参数从 JSON body 读取，避免前端桥接调用失败
- 通过 `python -m compileall` 语法检查，无语法错误

### 2026-11-15 - WebUI 三页面 + 单元测试
- pages/dashboard：各机厅排卡看板、黑名单列表、一键清零 / 修改人数 / 解除黑名单
- pages/arcades：机厅 CRUD、机台配置、方位别名配置、参数校验
- pages/settings：消息解析测试 + 操作日志
- tests 覆盖 parser / validation / store / service，修复 helpers.py `aliases or [...]` 覆盖空列表问题、机台别名配置、解析前归一化
- 55 个测试用例全部通过

### 2026-11-15 - help 指令 + 面板用法说明（本次需求）
- config.py 新增 `HELP_EXACT` / `HELP_CONTAINS` 触发词常量
- service.py 新增 `is_help_request()` / `help_hint()` / `build_help()`；`handle_event` 入口优先检测 help（任何群可用、无需绑定机厅，命中回复规范格式 + 示例，绑定机厅时附带机台 / 方位 / 别名明细）
- 异常报卡 `format_error()` 与连续异常调侃 `llm_tease()` 回复末尾追加「发送 help 查看格式」提示
- pages/settings 新增「报卡用法说明」卡片（格式 / 示例 / 含义表格），补充 `code` 样式
- tests 新增 4 个用例（触发词判定、绑定 / 未绑定群 help 回复、异常回复附 help 提示），59 个用例全部通过
- README.md 补充 help 指令说明

### 2026-11-15 - 打包 zip + 打包规范写入备忘录（本次需求）
- 按 AstrBot 安装规范将插件打包为 `e:\Program\maimai_card_report.zip`（53.1KB），可直接在面板上传安装
- 白名单复制核心文件：main.py / metadata.yaml / _conf_schema.json / astrbot_compat.py / config.py / utils.py / __init__.py / README.md / LICENSE + backend / mixins / pages 三目录
- 排除 reference / tests / history.md / __pycache__ / *.pyc / .gitignore / data
- 核实源码 `_get_plugin_dir_name_from_metadata()`：zip 顶层文件夹名 = metadata.yaml 的 name 字段（maimai_card_report），安装后落盘到 `data/plugins/maimai_card_report/`
- 本备忘录新增「打包发布（zip）详细步骤」章节：含关键事实、白名单清单、可复现 PowerShell 脚本、校验清单、常见坑，供后续 AI Agent 无脑执行不出错

### 2026-11-15 - 修复前端桥接 bug（页面打开报 Cannot read properties of undefined (reading 'apiGet')）
- 现象：安装成功后打开任一 WebUI 页面即显示「加载失败：Cannot read properties of undefined (reading 'apiGet')」
- 根因：AstrBot 4.29.3 自动把 bridge-sdk.js 注入到 `</body>` 之前（`astrbot/dashboard/services/plugin_page_service.py::process_plugin_page_html()`），晚于页面 body 内联 `<script>` 执行，导致脚本执行时 `window.AstrBotPluginView` 尚未定义
- 修复：三个页面（dashboard / arcades / settings 的 index.html）在 `<head>` 中显式引入 `<script src="/api/plugin/page/bridge-sdk.js"></script>`；AstrBot 会用该标签重写 URL（补 token）且因字符串已存在不会重复注入
- 依据：官方文档 plugin-pages.md「内联脚本必须同步访问 window.AstrBotPluginView 时，请在脚本前显式引入 bridge-sdk.js」；并核实 bridge-sdk.js 源码 `apiGet`/`apiPost` 不依赖 `ready()`（直接 postMessage）
- 已重新打包 `e:\Program\maimai_card_report.zip`（53.3KB），验证 zip 内三个页面均含 bridge-sdk.js 引入
- 本备忘录「参考项目学习笔记」补充「前端桥接关键坑」条目，防止后续再犯

### 2026-11-15 - 修复页面顶部只显示「加载失败」且无原因
- 现象：引入 bridge-sdk.js 后 `Cannot read properties of undefined` 消失，但页面顶部只显示「加载失败」四个字，无任何原因
- 根因：AstrBot 前端 SDK 转发插件 API 响应时 `sendBridgeResponse(requestId, true, response.data?.data ?? response.data)` 会**无条件解包 `data` 字段**。后端返回 `{"ok": true, "data": 业务数据}`，前端 `apiGet` 拿到的是业务数据本身（无 `ok` 字段），前端 `if (!r.ok)` 误判失败 → `showError(r.message || '加载失败')` 因 `r.message` 为 undefined 而只显示「加载失败」
- 修复：三个页面（dashboard / arcades / settings 的 index.html）的 `get`/`post` 封装改为 async 并做兼容转换：`r && typeof r === 'object' && r.ok === false ? r : { ok: true, data: r }`；后端 `{"ok", "data"/"message"}` 结构保持不变
- 已重新打包 `e:\Program\maimai_card_report.zip`（53.4KB），验证 zip 内三个页面封装已更新且 bridge-sdk.js 引入仍在
- 本备忘录「参考项目学习笔记」补充「前端桥接数据解包关键坑」条目，防止后续再犯

### 2026-11-16 - 日志系统 + 浏览器访问说明 + 重新打包（本次需求）
- 新增 `log.py`：统一日志入口，AstrBot 环境复用 `astrbot.api.logger`，独立运行/单元测试回退标准 logging（`maimai_card_report` logger，INFO 级别，输出到 stderr）
- `main.py` 补充生命周期日志：初始化数据目录、WebUI API 注册成功/失败、定时任务启动/停止/循环启动、定时清零结果、定时任务异常
- `mixins/event_handlers.py` 补充消息链路日志：接收群消息（群号/发送者/原始文本）、处理结果、异常栈
- `backend/service.py` 补充业务日志：服务初始化、机厅匹配、报卡/查询结果、惰性清零、超时清零、异常处理、黑名单、LLM 调侃、开门/闭店语（无 Provider 回退、无群会话、发送失败、生成失败）
- `mixins/web_api.py` 重写 `_register_webui_api` 包装器：统一改用 `..log.logger`，记录每个 API 请求的方法/路由/耗时/状态码；4xx 记 WARN，5xx 与异常记 ERROR（含堆栈）
- `backend/store.py` 补充持久化日志：数据加载数量汇总、JSON 读取失败（含路径）、保存失败（含路径）
- README.md 补充「浏览器访问地址」章节：`http://localhost:6185/plugin/maimai_card_report/[dashboard|arcades|settings]`，说明页面在 AstrBot 前端 iframe 内运行、桥接 SDK 由 AstrBot 注入、勿直接打开数据目录 index.html
- README.md 补充「日志系统」章节：诊断日志（AstrBot 标准日志通道，面板「日志」页 + `{AstrBot 数据目录}/logs/`）与操作日志（`{AstrBot 数据目录}/plugin_data/maimai_card_report/logs.json`）双通道说明
- 打包白名单新增 `log.py`（根目录文件与脚本 `$rootFiles`、校验清单同步更新），重新打包 `e:\Program\maimai_card_report.zip`（57.1KB）
- 验证：`python -m compileall` 通过；59 个单元测试全部通过（`Ran 59 tests ... OK`）

### 2026-11-16 - 修复默认打开页为「机厅管理」而非首页（本次需求）
- 现象：点击 AstrBot 管理面板进入插件，默认打开「舞萌报卡 · 机厅管理」（机厅管理页），而非首页看板
- 根因：`discover_plugin_pages()`（`astrbot/dashboard/services/plugin_page_service.py`）对 `pages/` 子目录 `sorted(..., key=lambda item: item.name.lower())` **按目录名字典序**排列，前端侧边栏与「点击插件默认打开」都取 `pages[0]`；原目录 `arcades` < `dashboard` < `settings`，`arcades`（机厅管理）排在首位成为默认页
- 修复：`pages/` 目录重命名加数字前缀控制顺序——`dashboard`→`1-dashboard`、`arcades`→`2-arcades`、`settings`→`3-settings`，使 `1-dashboard`（首页看板）字典序第一
- 新增 `.astrbot-plugin/i18n/zh-CN.json`、`en-US.json`：用 `views.<view_name>.title` 把侧边栏显示名映射回「首页看板 / 机厅管理 / 设置与调试」（`view_name` 必须与目录名一致），避免数字前缀显示到 UI；同时映射 `metadata.display_name`
- README.md 更新「浏览器访问地址」三页 URL 为 `1-dashboard`/`2-arcades`/`3-settings`，并补充数字前缀原因说明；「项目结构」同步更新目录名与 `.astrbot-plugin/i18n`
- 打包白名单新增 `.astrbot-plugin/` 目录（脚本 `Copy-Item` 与校验清单同步更新），重新打包
- 本备忘录「参考项目学习笔记」补充「页面排序与默认打开页关键坑」条目，防止后续再犯

### 2026-11-16 - 插件页面内新增导航栏（本次需求）
- 现象：默认打开页已修复为首页，但插件页面（iframe）内部没有侧边栏/导航，首页里无法操作也切换不到其他页面
- 根因（官方设计而非 bug）：AstrBot 插件视图以受限 iframe 嵌入 `PluginViewPage.vue`，**iframe 内部不注入任何导航组件**，页面切换依赖父页面左侧全局侧边栏；而全局侧边栏默认（未按插件分组）只取每个插件的 `pages[0]`（即第一个页面），其余页面被折叠，用户看不到入口。官方文档 `plugin-pages.md` 明确插件视图只负责 iframe 内内容渲染
- 修复（官方规范内、无 hack）：在三个页面 `pages/*/index.html` 顶部各加一条**页面内顶部导航 tab 栏**（首页看板 / 机厅管理 / 设置与调试，当前页高亮），点击后 iframe 自行跳转到对应视图
- 实现要点：从 `window.location.pathname` 解析当前视图名与 token（路径形如 `/api/v1/plugins/<plugin>/views/<view>/_t/<token>/`），用正则 `^(.*\/views\/)[^\/]+(\/_t\/[^\/]+\/.*)$` 提取前缀与 `/_t/<token>/...` 后缀，替换中段视图名并保留 `window.location.search`（theme 参数）重建兄弟页 URL，`<a href>` 触发 iframe 自身导航
- 兼容性说明：该导航仅依赖 URL 结构，不依赖 bridge 上下文（bridge 未提供页面内导航 API），故即使父页面 context 中 `pageName` 仍为旧值也不影响页面渲染（三个页面只用 `apiGet`/`apiPost`，未用 `getContext`/`pageName`）
- 重新打包 `e:\Program\maimai_card_report.zip`（59.9KB），校验清单逐项通过
- ⚠️ 后续发现此方案**不可行**（点击其他页返回 `{"status":"error","message":"Token 无效"}`），已被下一条记录推翻并改回单视图页签方案，勿再沿用上述「URL 拼接跳转」思路

### 2026-11-16 - 修复导航切换报「Token 无效」：合并为单视图页签（本次需求）
- 现象：点击页面内顶部导航栏跳转其他页时，返回 `{"status":"error","message":"Token 无效"}`
- 根因：AstrBot 为每个插件视图签发的 JWT 资源 token 与 `page_name`（视图名）绑定。后端 `require_plugin_view_token`（`astrbot/dashboard/api/plugins.py`）校验 `payload.get("page_name") != request.path_params.get("view_name")` 即抛「Token 无效」401。页面内导航直接复用当前视图的 token 去访问兄弟视图，token 里的 `page_name` 仍是旧视图名，校验必然失败
- 关键约束（逐一核实源码，确认无 hack 空间）：
  - iframe 沙箱为 `sandbox="allow-scripts allow-forms allow-downloads"`，**无 `allow-top-navigation`**，页面内无法改父页面 URL/路由
  - `PluginViewPage.vue` 的 `loadPluginView` 只在进入视图时签发 token，父页面未向 iframe 暴露「切换视图」的 postMessage 接口（bridge 仅 `ready/getContext/apiGet/apiPost/upload/download/subscribeSSE`）
  - `plugin_page_bridge.js` 亦无任何页面内导航 API
- 结论：多视图拆分在 AstrBot 中无法实现「页面内互跳」，只能依赖侧边栏「按插件分组」子菜单，但侧边栏默认不分组（`groupByPlugin` 默认 false，只取 `pages[0]`），用户根本看不到切换入口 → 拆多视图 = 用户无法切换
- 修复（根治）：把三个页面**合并为单个 `pages/dashboard/index.html` 控制台**，顶部用 JS 页签（首页看板 / 机厅管理 / 设置与调试）在 iframe 内部切换，切页签时按需刷新对应区块数据；所有桥接 API 仍走同一视图的 token，不再跨视图，彻底消除 Token 无效
- 同步改动：
  - 删除 `pages/1-dashboard`、`pages/2-arcades`、`pages/3-settings` 三个目录
  - `.astrbot-plugin/i18n/zh-CN.json`、`en-US.json`：`views` 键由三页改为单个 `dashboard`（zh「控制台」/ en「Console」）
  - README.md：「WebUI 控制面板」「浏览器访问地址」「项目结构」改为单视图 `dashboard`，访问地址 `http://localhost:6185/plugin/maimai_card_report/dashboard`，并新增「为何合并为单页面」说明
  - 顺带修复 `pages/dashboard` 中机厅保存接口笔误：`post('arcades/save')` → `post('arcades')`（后端注册的 POST 路由是 `arcades`，`arcades/save` 不存在会导致「未找到该路由」）
- 重新打包 `e:\Program\maimai_card_report.zip`，按「打包后校验清单」逐项核对

### 2026-11-16 - 修复群消息误识别（问号 / 「人」字触发误报卡与误查询）
- 现象（实机日志确认）：
  - 消息末尾带问号（如「现在？」「不是？」）被 `is_query()` 误判为查询，返回排卡结果
  - 普通含「人」的群聊（如「又不是每个人都有这么多号」「我那天还是别人请的」）被 `looks_like_report_attempt()` 误判为异常报卡，触发报错回复
- 根因：
  - `is_query()` 只要文本含单个 `?` 就返回 True，未校验问号前后是否为有效查询词
  - `looks_like_report_attempt()` 无长度 / 结构约束，只要文本含「人」且无数字即触发异常报卡判定
- 修复（`backend/parser.py`）：
  - `is_query()` 改为仅当「jk」、`几`+卡数单位（k/卡/人）、`?`+卡数单位（k/卡/人）时才返回 True；句末孤立问号、普通英文 `ok` 等不再触发
  - `looks_like_report_attempt()` 增加三重兜底：① 长度 ≤12 字符；② 去掉所有报卡相关原子（数字/卡/k/人/方位别名/机台别名）后无残留（`_report_residue` 为空）；③ 必须含明确报卡信号（数字 / k / 卡 / 人 / 方位 token），否则返回 False
- 验证：`tests/test_parser.py` 新增「现在?」「不是?」「?k」「?卡」等用例，`python -m unittest discover -s tests -t .` 全部通过（67 → 69）

### 2026-11-16 - 修复非默认机台超时清零后无「清零于」提示（本次需求）
- 现象：超过 4 小时清零后，默认机台（舞萌）查询显示「0 人（4小时无人报卡，清零于 X）」，但非默认机台（太鼓达人）仍显示陈旧的「更新于 X」
- 根因：`service.py` 的 `lazy_clear_machine()` 只清零 `count > 0` 的记录并写入 `last_clear_at`；非默认机台的方位记录此前已被报成 0 人（`count == 0`），从未再触发清零，因此 `last_clear_at` 一直为 0，`_machine_query_lines()` 中 `count <= 0 and cleared_at > 0` 分支永远不会命中，只能落到「更新于」分支
- 修复（`backend/service.py` 的 `_machine_query_lines()`）：对「人数为 0、从未触发过清零、且 `now >= record_expire_at`」的记录，将 `cleared_at` 视为该记录的过期时刻，同样走「0 人（…小时无人报卡，清零于 …）」分支，使非默认机台与默认机台提示一致
- 验证：`tests/test_service.py` 新增 `test_query_stale_zero_count_non_default`（非默认机台过期 0 人应显示「清零于」）、`test_query_fresh_zero_count_not_cleared`（未过期 0 人仍显示「更新于」且不含「清零于」），全部通过
- 重新打包 `e:\Program\maimai_card_report.zip`，按「打包后校验清单」逐项核对

### 2026-11-17 - 修复裸数字误报 + 实现真正的扣减报卡（本次需求）
- 问题一：群内裸数字被当成报卡
  - 现象：「6」直接写成左 6；「666」「2026」「114514」被判超范围异常，累计 5 次会被封禁（实机群聊高频词，风险极高）
  - 根因：`backend/parser.py` 的 `extract_signed_count()` 正则 `^([+-]?)(\d+)(?:[k卡人])?$` 中单位为可选，裸数字直接命中；`looks_like_report_attempt()` 只要含数字就视为报卡尝试，导致裸数字进一步计入异常
  - 修复：`extract_signed_count()` 改为必须带单位（k/卡/人）或显式正负号，返回 `(mode, count)`（set/add/sub）；`looks_like_report_attempt()` 新增 `_has_report_signal()`，只认「单位 / 行首符号+数字 / 方位别名」三类信号，裸数字与 `2026-11` 这类日期文本不再触发
- 问题二：README 声称支持扣减 `-`，实际 `z-1` 被解析成 `count=-1` 并被判为「负数异常」，扣减功能从未真正生效
  - 解析层：`_position_pattern` 为「数字+方位」分支补 `sign1` 捕获；`ParsedEntry` 新增 `decrement` 字段，`count` 统一保存非负变动量，`+`→累加、`-`→扣减、无符号→覆盖
  - 业务层：`service.handle_report()` 按 `decrement` 计算 `max(0, old - n)`，扣减后最低为 0；移除不再可达的「负数异常」分支
  - 持久化：数值未变化时跳过写入，避免「左-1」在 0 人时刷新 `last_update_at`，把「清零于」显示成「更新于」
  - WebUI：`/parse` 接口返回 `decrement`，解析测试页按「覆盖 / 累加 / 扣减」显示
- help 文本更新：`build_help()` 增加扣减语法（`z-1` / `左-2` / `-1k` / `-2卡`）、明确「数字必须带单位」，并提示「单独发送数字不会报卡」；README、metadata.yaml、控制台「报卡用法说明」同步
- 群响应规则保持不变：help 在未绑定群不可达、未在机厅管理绑定的群一律静默（`event_handlers.py` 的 `is_managed_group` 前置校验未改动）
- `llm_tease()` 健壮性：新增 `ReportService._resolve_provider()`，统一处理 `context is None`、`context` 缺少 `get_using_provider_async`、Provider 调用抛错三种情况，均回退默认文案；`_generate_notice_text()` 与 `_send_notice()` 同步改用该 helper，后者补 `context / send_message` 判空
  - `context` 含义：AstrBot 注入 `Star` 的 Core 上下文（`main.py` 中 `ReportService(self.store, context)`），是取模型、主动发消息、注册 Web API 的唯一入口；生产环境恒非空，仅单测/本地回退 `ReportService(store, None)` 时为空，旧版 AstrBot 还可能缺少相关方法
- 验证：`python -m unittest discover -s tests -t .` 81 个用例全部通过（70 → 81），新增裸数字忽略、扣减、扣减归零、无记录扣减不落盘、context 为空回退等用例；`python -m compileall` 通过
- 版本号：`metadata.yaml` 1.0.0 → 1.1.0
- 重新打包 `e:\Program\maimai_card_report.zip`（59KB）：白名单新增 `requirements.txt`，已按「打包后校验清单」核对顶层目录、必需文件与排除项

### 2026-11-17 - 修复群消息无差别响应 + 开门/闭店语未发送（本次需求）
- 问题一：插件无差别响应所有群聊消息，应只响应已在机厅管理添加（绑定）的群
  - 现象（实机日志 logs.json）：大量未绑定群（1059887064 / 1128316483 / 817182300 / 860816261）的普通消息被接收并写入「收到群消息 / 处理结果」日志，仅在「未匹配机厅」阶段静默跳过，导致日志繁杂
  - 根因：`mixins/event_handlers.py` 的 `on_group_message` 用 `@filter.event_message_type(ALL)` 无条件监听所有消息，入口无群白名单前置校验
  - 修复：`backend/service.py` 新增 `is_managed_group(group_id)`（判断群号是否存在于任意机厅 `group_ids`）；`on_group_message` 在写日志前先做该校验，非绑定群直接静默返回（顺带过滤私聊，因 `get_group_id()` 为空）
- 问题二：机厅管理设置的开店/闭店语从未发送
  - 现象：state.json 中 `last_open_notice` / `last_close_notice` 全为空，日志无开门/闭店语相关条目
  - 根因：定时任务 `_scheduler_loop` 只在 `@filter.on_astrbot_loaded()` 钩子里启动；该钩子仅在 AstrBot 核心启动时触发一次，插件通过 WebUI 安装/刷新重载时不会触发（已核实 `core_lifecycle.py` 仅在启动时 dispatch，`proactive_chat` 参考插件也注释「插件重载等钩子不会触发」），故重载后定时任务从未运行
  - 修复：`main.py` 新增幂等的 `_ensure_scheduler_started()`，在 `initialize()` 中启动定时任务（AstrBot 官方 `register_task` 已弃用并提示「在 initialize() 中启动后台任务」）；`on_astrbot_loaded` 保留作兜底
- 排查日志发现的其他潜在问题（待用户确认是否修复）：
  1. 游梦岛（1048131348）在 `group_sessions` 中无会话记录：开门/闭店语依赖 `group_sessions` 主动发消息，该群从未发过消息，修复后真快活（428980508）能正常发送，游梦岛仍会走「无可用群会话」分支，需该群有人发一条消息后才能补上会话
  2. 开门/闭店是「精确到分钟」匹配（`arcade.open_time == current_hm`）：30 秒轮询通常能命中，但若插件恰好在目标分钟内后半段启动/重载，当天那次会漏发
  3. `group_sessions` 只增不减：历史残留 4 个已解绑群的会话映射（1059887064 / 1128316483 / 817182300 / 860816261），本次群白名单修复后不再新增非绑定群会话，但旧残留仍在（影响很小）
- 验证：`tests/test_service.py` 新增 `test_is_managed_group`，`python -m unittest discover -s tests -t .` 全部通过（69 → 70）
- 重新打包 `e:\Program\maimai_card_report.zip`（57.2KB），按「打包后校验清单」逐项核对
### 2026-11-17 - 发布到 GitHub（ty-2333/astrbot_plugin_maimai_card_report）
- 背景：项目自插件模板 `Soulter/helloworld` 拉取，`metadata.yaml` 的 `author` / `repo` 仍是占位值 `Tool-yang`，且 `origin` 仍指向模板仓库，从未推送过自己的代码
- 元数据修正：`metadata.yaml` 的 `author` → `ty-2333`、`repo` → `https://github.com/ty-2333/astrbot_plugin_maimai_card_report`
- 远端调整：`origin` 从 `https://github.com/Soulter/helloworld.git` 改为新仓库；本地分支 `master` 重命名为 `main`（与账号下其他仓库一致）
- 忽略规则补充：`.gitignore` 新增 `reference/`（参考项目，约 20MB）、`data/`（运行时数据）、`*.zip`（打包产物），确保不随仓库推送
- 推送内容仅限插件本体：根目录脚本与配置、`backend/`、`mixins/`、`pages/`、`.astrbot-plugin/i18n/`、`tests/`、`README.md`、`LICENSE`、`history.md`、`requirements.txt`
- 排除项：`reference/`（第三方参考项目）、`data/`（本地运行数据）、`__pycache__/`、`*.zip`
- 未改动：`history.md` 内历史条目中的 `Tool-yang` 属历史记录，保持原样
