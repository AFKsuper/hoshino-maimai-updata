# 本次实际验收报告

日期：2026-09-21。代码不是仅通过语法检查的示例，但**没有真实账户上传验收**。

历史发布排障记录（不代表当前发布状态）：用户指定的 `DEV_20260921` 实际位于 `Morus505/hoshino-maimai-updata`，是 AFKsuper 目标仓库的 fork。该分支基线同为 `715c1876ea03becb267dbfd816864cfec0712315`，当前连接对此 fork 返回 `push=true`，当时对 AFKsuper 原仓库是 `push=false`。当前GitHub登录身份已核实为Morus505；实际以38个已提交文本文件调用fork的create_tree，仍返回403 Resource not accessible by integration。说明账号仓库权限不能替代当前应用连接的实际写权限。写入后复查该分支仍在原始基线，未创建远程commit或PR。下节保留首次 ZIP 交付及原仓库写入受阻的历史记录。

## 首次交付时的仓库与权限记录

四个仓库均实际通过 `git ls-remote`、clone 和公开 GitHub API 读取成功，公开 API 的 `private=false`。默认分支及完整提交见 README 表格。目标仓库初始有 README，基线 `715c1876ea03becb267dbfd816864cfec0712315`；交付前再次 `ls-remote --symref` 确认 HEAD 仍是该提交。本地新分支 `feat/secure-score-upload`，没有覆盖用户后续提交、强推或修改三个参考仓库。

必须区分三层权限：

1. GitHub 用户本人角色：本次没有取得带用户认证的仓库权限响应，**未核实其管理员/写入角色**。
2. GitHub 应用安装/授权：本轮开始未安装，用户随后连接成功；再次查询确认 installed/enabled。显示的「允许低风险操作」是本应用执行审批偏好，**不是 GitHub Contents scope，也不是已选仓库的写权限证明**。没有要求改变 Contents 授权，没有将公开读取等同连接授权。
3. 当前会话实际能力：连接后重新发现，工具目录仍没有可调用的 GitHub 仓库读取、创建文件、分支、提交或 PR 工具；也没有 `gh`。终端可公开 clone，实际 `GIT_TERMINAL_PROMPT=0 git push --dry-run origin HEAD:refs/heads/feat/secure-score-upload` 返回：

```text
fatal: could not read Username for 'https://github.com': terminal prompts disabled
```

因此首次 ZIP 交付时未进行远程写入，当时没有远程提交/PR可声称。它不是历史上的403，也不说明用户或应用一定缺写权限，只说明当前执行路径没有取得可用的认证写入能力。工程以本地 Git 提交、ZIP 和 format-patch 交付；[导入命令](IMPORT_GIT.md)不含密码或令牌。

公开网页工具对四地址返回 DisabledError；终端实际 Git 和公开 API 成功，所以未将网页工具失败误报为仓库404。

## 实际环境与安装

- Linux x86_64，CPython **3.10.21**（独立虚拟环境）。
- nonebot **1.8.0**，aiocqhttp **1.4.2**，Quart **0.14.1**。
- maimai-py **1.5.2** / maimai-ffi **0.7.1**，HTTPX **0.28.1**，httpcore **1.0.9**。
- aiohttp **3.8.6**，Pillow **9.1.1**，zxing-cpp **2.2.0**，cryptography **46.0.3**。
- pytest **8.3.5** / pytest-asyncio **0.24.0**；测试二维码由 qrcode **7.4.2**生成。
- 完整本次环境版本见 [test-environment.txt](test-environment.txt)，共69包。这是实测环境记录，不要求往已有机器人里强制安装整份列表。

**安装证据与局限：** 初次合并原 Hoshino `requirements.txt` 与插件依赖求解成功（86包，没有发现同环境必然冲突）。实际安装在 `matplotlib==3.2.2` 本机编译时失败，先缺 FreeType，设置其官方 `MPLLOCALFREETYPE=1` 后构建因执行 `./configure` 权限失败。没有绕过权限或修改原 Hoshino 核心版本来掩盖结果。

因此单独安装原版本 NoneBot/Quart/aiocqhttp 与本插件所需依赖完成验证；为导入 Hoshino 的通用 util（它强制导入matplotlib），**仅隔离冒烟环境**安装有 wheel 的 `matplotlib==3.5.3`，保留原兼容的 `numpy==1.22.4`。不能声称完整原始 Hoshino requirements 原样安装成功，也未实测全量 Hoshino 其他功能。正常已有 Hoshino 环境不需要为插件升级 matplotlib。Python3.8不适用maimai-py；其他系统/版本未验证。不需要独立成绩后端进程，本次代码在机器人同一环境运行。

## 实际执行命令与结果

以下为工作区真实命令；`.venv` 是上述 CPython3.10.21 环境，`project` 是目标仓库checkout：

```bash
uv pip check --python .venv/bin/python
# Checked 69 packages; All installed packages are compatible

.venv/bin/python -m compileall -q project
# exit 0

.venv/bin/python -m pytest project/tests -q
# 173 passed in 1.05s

.venv/bin/python project/scripts/smoke_hoshino.py \
  --hoshino-source references/hoshino/HoshinoBot \
  --report project/docs/smoke-result.json
# exit 0, status PASS, 25 events, 5 mock_backend_submissions

git diff --check
# exit 0
```

复制到普通开发环境后可按README使用 `python -m pip check`。主测试命令本次使用 uv 的实际依赖检查，不伪称运行过虚拟环境未安装的 pip。

| 测试部分 | 实际范围 |
| --- | --- |
| 文本解析及上传核心（45项） | 空白/空串/异常字符/前缀/多码；实际安装的 maimai-py provider、Arcade转换、目标序列化、请求headers；真实HTTPX请求结构但MockTransport；FFI网络函数Mock；成功、错误凭据、200假失败、无分、部分失败、429/5xx、超时、取消、会话关闭、一次写入、不重试 |
| 图片（49项） | 真实生成不含账户信息的二维码并解码，多个二维码、空白/损坏/超限/动画；真实解码子进程及kill/回收；base64、file ID、get_image返回、POSIX本地白名单及符号链接；危险协议、数字IP变体、IPv6过渡、私网DNS、重定向、超时、大小；HTTP响应模拟；真实aiohttp解析器的DNS重绑定回归 |
| app/数据库/配置（65项） | 真实SQLite/Fernet；QQ隔离、行密文归属、权限、删记录与缓存、错key、环境变量、四入口统一后端、多图/多码拒绝、缺当前目标不换源、群绑定保护、普通图安静、并发、去重TTL、确定/不确定失败后状态释放、取消释放、日志不泄漏 |
| Hoshino路由（14项） | Service群总开关/自动开关、private黑名单、普通图安静、群误发凭据提示、动态旧命令冲突与节流、异常消息脱敏 |

**总计173项自动测试通过。** 测试不带真实用户二维码/密钥，也不访问其他账户。

## 真实 Hoshino 加载冒烟

交付脚本 [scripts/smoke_hoshino.py](../scripts/smoke_hoshino.py) 临时复制目标 Hoshino 原始源码与示例配置，装载 `maimai_updata` 和原 `botmanage`；使用真实 `hoshino.init()`、`nonebot.load_plugins()`、Quart `startup/shutdown`、`CQHttp._handle_event`。最初脚本只 init 未 startup 导致 enable 命令的 `bot.loop=None`，现已修正并实际重跑通过，未改插件去掩盖宿主生命周期。

最终 **25条合成事件PASS**，16个宿主发现模块加载（插件5、botmanage11），5次Mock上传。真实执行了：私聊绑定/选源/删凭据、未启用群不上传、原botmanage启用/禁用服务命令、群误发凭据拒绝、普通图安静、群自动图开关、私聊图片、显式命令附图、文本、目标缺凭据、用户隔离及重复提交保护。图片解码与加密数据库是真实实现。

Mock部分为 QQ `send`、`get_group_member_info`，以及成绩上传后端。**没有运行中QQ接入端，没有真实舞萌/水鱼/落雪账号调用。** 原始机器可读报告见 [smoke-result.json](smoke-result.json)。不会把5次Mock提交写成5次真实成绩上传。

## 尚未实机验证

- QQ接入端实际发来的图片URL/file及本机部署拓扑；OneBot兼容路径已按真实事件/API代码与fixture验证。
- 有效机台二维码获取真实成绩、机台网络可达性、查分器个人密钥实际权限/账户初始化，以及生产环境响应。
- 其他Python/OS/CPU、多进程、Hoshino全部非上传模块；多进程明确不支持共享本插件锁。
- 上游maimai-ffi是编译组件，不能声称已经审查其内部协议源码。

用户最小真实验收步骤与故障处理见 README 第5、6、8节。真实密钥只在用户本地/私聊输入，不提交公开仓库。

## 网页发布路径复核

2026-09-21，用户接受协作邀请后，连接返回 AFKsuper 仓库 `push=true`，但实际创建 Git tree 仍报403。浏览器登录 Morus505 后，GitHub 授权详情显示 ChatGPT Codex Connector 已授权账号身份，但未安装到任何可访问账号。原仓库网页提供上传及提交功能，因此转为网页新分支提交、PR审查与合并；最终发布状态以 GitHub 提交和 PR 记录为准。应用接口403与账号协作者权限是不同问题。
