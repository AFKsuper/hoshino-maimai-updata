# HoshinoBot / maimaiDX 源码核实记录

核实日期：2026-09-21。以下仓库均通过真实 `git ls-remote --symref` 和浅克隆读取；网页工具不可用不影响 Git 读取。这不代表 GitHub 应用写权限已获授权。

| 仓库 | 默认分支 | 实际检出的提交 |
| --- | --- | --- |
| AFKsuper/HoshinoBot | master | `781a902a4d701162d87456bebb7254a8803a4e31` |
| AFKsuper/maimaiDX | main | `562f92b85045ef7f94f79689ddc709ab0062ef39` |

## HoshinoBot 环境

README 标注 Python 3.8+，安装示例使用 Python 3.8；这并非对任意新 Python 的完整兼容承诺。没有锁文件。`requirements.txt` 包含：

```
Quart==0.14.1
MarkupSafe~=1.0
Jinja2~=2.11.2
werkzeug~=1.0.1
wsproto~=0.15.0
nonebot[scheduler]==1.8.0
aiocqhttp~=1.4.0
aiohttp~=3.8.1
Pillow~=9.1.0
matplotlib~=3.2.1
numpy~=1.22.3
```

其余依赖见上游原文件。本插件不安装完整 maimaiDX，也不升级上述核心框架。

已读取 PyPI 的 NoneBot 1.8.0 源码和 aiocqhttp 1.4 系列源码。NoneBot 1.8.0 声明 Python >=3.7；实测选择的 aiocqhttp 1.4.2 要求 Quart>=0.14,<0.15，与此 Hoshino 的 Quart==0.14.1 相容。aiocqhttp 1.4.4 要求 Quart>=0.17，不能盲目选择该小版本。完整环境的实测版本及结果见项目验收报告。

### 实际加载与启动

1. 配置由 `hoshino/config_example` 复制为 `hoshino/config`，主配置是 `hoshino/config/__bot__.py`。
2. `MODULES_ON` 是模块名集合。
3. `hoshino.init()` 对每个模块调用 `nonebot.load_plugins(hoshino/modules/<name>, 'hoshino.modules.<name>')`。
4. NoneBot 1.8 的 `load_plugins` 扫描该目录下非下划线开头的 `.py` 文件及有 `__init__.py` 的包。插件的 `handlers.py` 正由这一路径注册，仓库名的连字符不会被用作模块名。
5. 根目录 `run.py` 调用 `hoshino.init()`，并通过 `bot.run(use_reloader=False, loop=asyncio.get_event_loop())` 启动。

### Service 和消息边界

`Service(name, enable_on_default=False)` 提供按群配置。`_check_all(event)` 同时检查 `check_enabled(group_id)`、群黑名单和用户权限。群管发送 `启用 maimai-upload`；自动识图另需 `启用 maimai-upload-auto`。配置持久化到 `~/.hoshino/service_config/<ServiceName>.json`。

Hoshino 的 `msghandler.handle_message` 仅处理 `event.detail_type == 'group'`；`Service.on_prefix`、`on_fullmatch` 因此不能直接提供私聊绑定。`priv.check_priv` 对全部私聊返回 False。本插件用 aiocqhttp 的 `bot.on_message('private')` 明确注册私聊，直接遵守 Hoshino 用户黑名单；群聊用 `bot.on_message('group')` 并执行 Service 权限检查。

唯一不依赖群上传开关的提醒是用户误发到群里的凭据绑定命令：仅检查文本并提醒私聊及撤销或更换凭据，不读写数据库，不下载或识别图片；黑名单仍然有效。

aiocqhttp 的事件对象支持字典与属性访问，消息为 `Message` / `MessageSegment`，段包含 `type` / `data`，图片段可以带 `url`、`file` 等接入端提供的字段。本插件只把不透明 `file` 标识交给接入端 `get_image`，默认不把它当作服务器路径；具体适配和限制见 README。

### 日志风险已确认

NoneBot 1.8.0 的 `message.py::_log_message` 在预处理器之前以 INFO 记录 `repr(str(event.message))`，可能包含完整二维码和绑定凭据。Hoshino 也给 NoneBot 配置错误日志处理器。因此插件本身不记敏感内容，并不意味着上游机器人、QQ 接入端、代理或日志收集服务不会记录。管理员须检查并过滤原消息日志，设置日志保留期与访问权限；旧日志可能需要清理。仅关闭 Hoshino DEBUG 并不足以关闭这条 INFO 日志。

## maimaiDX 上传参考与命令冲突

现有源码 `core/upload.py` 已使用 `MaimaiClient.qrcode`、`ArcadeProvider.get_scores_all`、`MaimaiClient.updates`。`commands/mai_upload.py` 注册 `上传成绩` / `上传分数` / `传分`，以及 `水鱼导入token`、`落雪个人密钥`、`删除上传凭据`。旧实现仅处理文本，绑定虽然检查 private，但当前 Hoshino 的 prefix 调度本身不进入 private。旧项目的落雪可回退到开发者 Token + 好友码；本插件按用户要求只使用明确选定的目标和个人凭据，不自动回退。

maimaiDX 当前 requirements 包括 maimai-py>=1.5.1、Pillow~=12.2.0、numpy~=2.2.6、pydantic>=2.13.4、playwright>=1.60.0，明显不是原 Hoshino 的依赖组合。本插件仅参考上传流程，不整体引入绘图、浏览器、查歌等模块。

NoneBot 1.8 的多个 message_preprocessor 使用 `asyncio.gather` 并发，不能用新增预处理器抛 `CanceledException` 来保证旧上传不执行。aiocqhttp 按事件层级先执行 `message.group/private` 再执行 `message`；本插件不通过并发预处理器抢占旧处理器，也不悄悄改写旧插件。

本插件在启动和每次群消息检查 `hoshino.trigger.prefix.trie`；遇到同名或重叠命令、已核实的 `commands.mai_upload` 且旧服务在该群启用时，不进入本插件业务层。显式请求会收到每群最多每分钟一次的冲突提示，普通图片保持安静；旧处理器仍可能处理该消息，但本插件不会第二次提交。私聊仍可使用本插件，因为 Hoshino 的旧 prefix 不处理私聊。

为保留 maimaiDX 的其他功能，管理员在其 `commands/__init__.py` 删除或注释：

```python
from . import mai_upload as mai_upload
```

然后重启。也可在该群禁用整个旧 `maimaiDX` 服务，但其其他功能将同时停用。配置独立上传命令前缀不能自动解决旧凭据绑定命令冲突。对任意第三方自行注册的原始 OneBot 回调，插件无法发现或保证互斥，管理员应只启用一个成绩上传处理器。

## 许可证

HoshinoBot 仓库为 GNU GPL v3；maimaiDX 为 MIT，版权声明 `Copyright (c) 2021 Yuri-YuzuChaN`。本插件的 Hoshino 适配是依据公开接口独立实现，不复制其源文件；maimaiDX 上传流程作为参考。完整第三方声明见本项目对应许可文件。

## 实际加载冒烟

已运行 `python scripts/smoke_hoshino.py --hoshino-source <上述目标仓库克隆目录>`，通过真实 `hoshino.init()`、Quart startup/shutdown、aiocqhttp `CQHttp._handle_event()` 和 NoneBot 1 的调度，共 25 条测试事件，加载本插件 5 个子模块及 `botmanage` 的 11 个子模块。

实际验证了群管启用/禁用两种服务、私聊绑定、群误发凭据拒绝、文本上传、私聊和群聊二维码图片、命令加图片、普通图片安静、目标切换、缺少凭据、不同 QQ 隔离与删除。QR 图片由测试现场生成，真实解码；数据库真实加密读写。QQ 消息发送/群成员查询及成绩获取上传被 Mock，产生 5 次 Mock 后端提交；没有连接真实 QQ，没有进行真实舞萌上传。

该加载环境是 Python 3.10.21、NoneBot 1.8.0、aiocqhttp 1.4.2、Quart 0.14.1、Pillow 9.1.1、aiohttp 3.8.6、numpy 1.22.4。Hoshino 与插件都不改动；其 `util` 导入需要 matplotlib，本次使用可安装的 matplotlib 3.5.3。原 requirements 的 matplotlib 3.2.2 在该 Python 环境因缺少 FreeType 构建条件未能安装，因此本结果不等同于上游全部原始 requirements 完整安装通过。
