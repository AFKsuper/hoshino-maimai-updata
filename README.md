# hoshino-maimai-updata

独立安装到 **HoshinoBot / NoneBot 1** 的舞萌 DX 成绩上传插件。安装模块名为 `maimai_updata`，不是带连字符的仓库名。

项目发布仓库：`AFKsuper/hoshino-maimai-updata`。安装使用 `main` 分支；开发与发布验证过程见 [验收报告](docs/VALIDATION.md)。

支持私聊、已启用服务的群聊；`上传成绩 SGWCMAID…`、直接发送舞萌二维码图片、`上传成绩`附图均进入同一个 `Application → MaimaiUploader` 流程。每个 QQ 独立绑定凭据、选择水鱼或落雪，无自动切换平台。第一版不包含 B50、绘图、查歌、猜歌。

**验证边界：本工程没有使用真实账户、有效出勤二维码或在线 QQ 接入端完成真实上传。** 已执行的测试、精确命令、上游提交和依赖安装限制见 [验收报告](docs/VALIDATION.md)。Mock 只验证行为，真实 maimai-py provider 的请求序列化另有 HTTP transport 测试；这仍不等于生产平台实测。

## 1. 已核实的环境与上游

| 项目 | 本次读取的默认分支 / 提交 | 结论 |
| --- | --- | --- |
| [目标仓库](https://github.com/AFKsuper/hoshino-maimai-updata) | main / `715c1876ea03becb267dbfd816864cfec0712315` | 起始状态有 README 和初始提交，不是空仓库；在新分支开发 |
| [HoshinoBot](https://github.com/AFKsuper/HoshinoBot/tree/781a902a4d701162d87456bebb7254a8803a4e31) | master / `781a902a4d701162d87456bebb7254a8803a4e31` | NoneBot 1.8.0、aiocqhttp 1.4.x、Quart 0.14.1；README称 Python 3.8+ |
| [maimai.py fork](https://github.com/AFKsuper/maimai.py/tree/9a02bc6f9026d4af238ace3fabe9fc399cfa5367) | main / `9a02bc6f9026d4af238ace3fabe9fc399cfa5367` | 项目版本 1.5.1、Python 3.9+、maimai-ffi 0.7.0 |
| [maimaiDX](https://github.com/AFKsuper/maimaiDX/tree/562f92b85045ef7f94f79689ddc709ab0062ef39) | main / `562f92b85045ef7f94f79689ddc709ab0062ef39` | 参考 `core/upload.py`、`commands/mai_upload.py`，未修改仓库 |
| 实际选用 [maimai-py](https://pypi.org/project/maimai-py/1.5.2/) | PyPI 1.5.2 / ffi 0.7.1 | 已下载和读取 wheel 源码；1.5.2 包含落雪个人密钥鉴权分类等修复 |

本插件的交付验证环境是 **Linux x86_64、CPython 3.10.21**。源码使用 Python 3.9+ 特性，**不要安装到 Python 3.8**；其他 Python、操作系统和 CPU 架构需要自行验证 maimai-ffi/zxing-cpp wheel。使用已经正常运行的 HoshinoBot Python 3.10 环境最省事。没有引入 NoneBot 2，也没有升级 NoneBot、Quart 或 aiocqhttp 来适配插件。

`requirements.txt` 固定插件直接依赖；`requirements-dev.txt` 用于测试。原 Hoshino `matplotlib~=3.2.1` 在本次干净 Python 3.10 环境需要本机编译，实际因 FreeType/构建权限失败。真实 Hoshino 加载冒烟使用的绘图库版本及范围以验收报告为准；它不应被误解为完整原 requirements 原样安装成功。插件本身不依赖绘图库，不要求替换一个已经工作的 matplotlib。

详细接口证据：[maimai-py](docs/UPSTREAM_MAIMAI.md)、[HoshinoBot](docs/UPSTREAM_HOSHINO.md)。

## 2. 安装到正在运行的 HoshinoBot

先停止机器人并备份环境。以下命令在 **HoshinoBot 根目录**执行；将 `python` 换成实际运行 `run.py` 的虚拟环境解释器，例如 `/opt/hoshino/venv/bin/python`，不要把依赖装到另一个系统 Python 中。

```bash
cd /absolute/path/HoshinoBot
python --version
python -m pip freeze > /absolute/path/outside/repo/hoshino-before-upload.txt
# 在 HoshinoBot 根目录执行：
git clone --branch main --single-branch https://github.com/AFKsuper/hoshino-maimai-updata.git hoshino/modules/maimai_updata
# AFKsuper 原仓库合并后也可从原仓库安装；使用ZIP的方式见下文。
python -m pip install -r hoshino/modules/maimai_updata/requirements.txt
python -m pip check
```

ZIP 安装：将 ZIP 内的 `maimai_updata/` 整个目录解压到 `HoshinoBot/hoshino/modules/`。确认路径是 `hoshino/modules/maimai_updata/handlers.py`，不要再套一层仓库名。已有同名插件时先备份并比较，不要直接覆盖。

原仓库配置来源是 `hoshino/config_example`。已经运行的机器人直接编辑现有 `hoshino/config/__bot__.py`，**不要覆盖整份配置**；在 `MODULES_ON` 中添加：

```python
MODULES_ON = {
    # 保留原有模块，例如 botmanage
    'maimai_updata',
}
```

`hoshino.init()` 会调用 NoneBot 1 的 `load_plugins(.../modules/maimai_updata, 'hoshino.modules.maimai_updata')`，发现 `handlers.py` 并注册群聊、私聊事件。模块不创建第二个独立 QQ 机器人。

## 3. 管理员配置（启动前完成）

在仓库外创建受限的环境文件，示例使用当前运行用户的配置目录：

```bash
mkdir -p "$HOME/.config/hoshino" "$HOME/.local/share/hoshino/maimai_updata"
chmod 700 "$HOME/.config/hoshino" "$HOME/.local/share/hoshino/maimai_updata"
# 同一个 Hoshino Python 环境生成随机密钥并写文件，不在终端打印密钥：
python - <<'PY'
import os
from pathlib import Path
from cryptography.fernet import Fernet
p = Path.home() / '.config/hoshino/maimai-upload.env'
with p.open('x') as f:
    os.chmod(p, 0o600)
    f.write('MAIMAI_UPLOAD_KEY=' + Fernet.generate_key().decode() + '\n')
    f.write('MAIMAI_UPLOAD_AUTO_IMAGES=true\n')
PY
set -a
. "$HOME/.config/hoshino/maimai-upload.env"
set +a
python run.py
```

文件已存在时不要再次生成覆盖密钥；恢复原文件。systemd 可在**机器人运行服务**中添加 `EnvironmentFile=/absolute/path/maimai-upload.env`，重载配置后重启。插件使用 `os.environ`，**不会自动读取 `.env`**；`.env.example` 列出的变量确实被 `Config.from_env()` 读取。不要将密钥写入模块源码或 Git。

| 环境变量 | 默认值 / 作用 |
| --- | --- |
| `MAIMAI_UPLOAD_KEY` | 必填 Fernet 密钥；未配置时拒绝保存/读取凭据，不降级明文 |
| `MAIMAI_UPLOAD_DATA_DIR` | `~/.local/share/hoshino/maimai_updata`，位于仓库外 |
| `MAIMAI_UPLOAD_AUTO_IMAGES` | `true`；控制所有被动图片识别，群聊还需要专门服务开关 |
| `MAIMAI_UPLOAD_BARE_CODES` | `true`；允许直接发 SGWCMAID 文本 |
| `MAIMAI_UPLOAD_COMMAND` | `上传成绩`；可改命令前缀，帮助文本同步变化 |
| `MAIMAI_UPLOAD_MAX_IMAGES` | 3，允许 1–5；任何图片读取失败均不从剩余图片选账户 |
| `MAIMAI_UPLOAD_CONCURRENCY` | 2，允许 1–8；涵盖识别和上传，不建立无界等待队列 |
| `MAIMAI_UPLOAD_COOLDOWN` | 5 秒，按 QQ 限流 |
| `MAIMAI_UPLOAD_DEDUP_TTL` | 120 秒，消息/成功或结果不确定的二维码去重 |
| `MAIMAI_UPLOAD_TIMEOUT` | 上传总体 120 秒 |
| `MAIMAI_UPLOAD_IMAGE_TIMEOUT` | 每图获取 10 秒 |
| `MAIMAI_UPLOAD_MAX_IMAGE_BYTES` | 8388608（8 MiB） |
| `MAIMAI_UPLOAD_MAX_PIXELS` | 12000000 |
| `MAIMAI_UPLOAD_LOCAL_IMAGE_ROOTS` | 默认空；仅用于受信任接入端 `get_image` 返回的本地目录，POSIX用冒号分隔 |
| `MAIMAI_UPLOAD_ARCADE_PROXY` | 默认空；管理员配置的可信 Arcade 代理，图片下载不会使用此代理 |

QQ 接入端需已经连接当前 Hoshino 的 OneBot v11/aiocqhttp。图片消息可携带 `url`、远程 `file`、`base64://`；不透明 `file` 标识通过实际 `get_image(file=...)` 解析。若返回的是另一个容器里的路径，必须配置同机共享且只存接入端图片的专用只读目录，或使接入端返回可用公网 URL。不要白名单 `/`、用户主目录或机器人源码目录。用户消息中的本地路径始终禁止读取。

图片只允许公网 HTTP(S) 的 80/443 端口；局域网 URL 不做例外放行。每次 DNS 和重定向都检查实际目标；不使用环境代理。允许静态 PNG/JPEG/GIF/WebP/BMP，拒绝动画；解码在可终止子进程进行，默认 5 秒墙钟上限、4 秒 CPU / 768 MiB 地址空间限制（POSIX），不阻塞事件循环。

## 4. 群启用与 maimaiDX 共存

服务默认全部关闭。保持原 `botmanage` 模块可用，由群管理者在目标群发送：

```text
启用 maimai-upload
启用 maimai-upload-auto
```

主服务控制群中上传及配置命令；即使主服务未启用，群里误发凭据绑定文本仍会收到私聊/更换凭据提醒，不读库、不扫描图片。第二个服务只控制**不带命令的图片自动识别**，还必须同时启用主服务、环境配置开关。只需要显式命令时仅启用主服务。停用：`禁用 maimai-upload-auto` / `禁用 maimai-upload`。实际服务配置保存在 `~/.hoshino/service_config/`。群黑名单、用户黑名单和 `use_priv` 检查继续有效。

私聊通过明确注册的 `bot.on_message('private')` 处理，遵守 Hoshino 用户黑名单，不使用会拒绝全部私聊的 `priv.check_priv`；群服务关闭不影响私聊。普通图片、非舞萌二维码、被动识别失败都不回复；明确上传命令识别失败才提示。一个输入有多个不同舞萌码时要求一次一个。

已核实参考 maimaiDX 中也有 `上传成绩`、`水鱼导入token`、`落雪个人密钥` 等命令。**不要同时启用两套上传处理器。** 对该提交版本，管理员可在已安装 maimaiDX 的 `commands/__init__.py` 中关闭 `from . import mai_upload as mai_upload` 这一上传模块导入，随后重启；保留查歌、B50 等其他模块。请先确认本机版本并备份，工程不会修改 maimaiDX。

本插件每条群消息检查 Hoshino 前缀注册表及冲突服务开关；发现已启用的旧处理器时自身拒绝整个群请求，提示最多每群一分钟一次，避免同一消息由本插件再次上传。旧处理器是否上传由其自己决定。私聊仍可走本插件，因为参考 Hoshino 的旧群前缀入口不处理私聊。只改上传前缀不能解决旧绑定命令冲突。未通过 Hoshino 注册表自行监听图片的其他第三方上传器不在可检测范围，管理员必须关闭它们。

## 5. 用户使用：绑定到首次上传

先添加机器人好友，**私聊**任选一个目标绑定：

```text
水鱼导入token <自己的导入Token>
上传源 水鱼
```

或：

```text
落雪个人密钥 <自己的个人API密钥>
上传源 落雪
```

水鱼使用「导入 Token」：实际请求头为 `Import-Token`，不是开发者 token、密码或登录 Cookie。落雪使用个人 API 密钥：实际为 `X-User-Token` 个人接口；不是应用 Client Secret/开发者 token。本插件不使用开发者 token + 好友码模式，两者都**不需要另填 QQ、用户名或好友码**。默认目标水鱼；绑定不会隐式切换目标。选择目标后若未绑定就提示绑定，不会上传至另一平台。

私聊查看 `上传配置`，确认源和绑定状态，然后提交自己刚取得的有效舞萌码：

```text
上传成绩 SGWCMAIDxxxxxxxx
```

`xxxxxxxx`只是占位说明，**不是有效二维码或固定长度规范**。源码只做有界输入、SGWCMAID 前缀与不可接受字符检查，真实有效性/过期由 maimai-ffi/舞萌服务判断。也可直接发有效二维码原图，或发送 `上传成绩` 并附图。两种入口进入同一上传器，识别不会把普通图片当账户提交。

其他命令：

| 命令 | 行为 |
| --- | --- |
| `舞萌上传帮助` | 返回当前配置前缀的帮助 |
| `上传配置` | 仅显示平台、已绑定/未绑定，不显示凭据 |
| `删除上传凭据` | 删除当前 QQ 所有凭据和目标偏好，并清理该用户缓存 |
| `删除水鱼token` / `删除落雪密钥` | 只删除自己的指定平台凭据 |

绑定只能私聊，群中绑定命令不会写数据库、不会回显密钥，并提醒撤销已泄露凭据。配置或上传正在进行时，同用户第二个操作被拒绝，完成后再删除/切换。

## 6. 上传确认与故障处理

上传器复用真实 maimai-py 的二维码身份获取、Arcade 成绩转换、查分器 provider 序列化与上传。每次请求独立 client，关闭 HTTP 和缓存；目标写入禁用 maimai-py 默认的三次 RequestError 重试。不会因超时盲目重发。

Arcade 接口只能取得达成率和 DX 分等数据，无法新增缺失的 FC/FS 信息。插件先用**同一用户所绑定凭据**读取目标平台旧成绩，保留其已有标记和较高值；读取失败会停止，避免破坏既有记录。不存在查询陌生 QQ/猜测账户的流程。

只有检查平台成功响应后才显示成功。显示的是实际序列化提交条数；水鱼响应提供的处理计数才用于确认数量，落雪未提供逐条入库数时明确说明，不宣称每条都成功。无有效成绩或全部被平台序列化过滤时不提交。异常响应、部分失败、限流、网络超时和凭据权限错误均有安全提示；不回显上游原文。

| 提示/症状 | 处理 |
| --- | --- |
| 未绑定当前目标 | 私聊绑定该源并用 `上传配置` 检查，不会自动换平台 |
| 二维码无效/过期/拒绝 | 重新取得自己当前二维码；不要反复发旧截图 |
| 舞萌服务器拒绝本机/连接失败 | 检查本机到舞萌服务网络；必要时由管理员配置合法可信 Arcade 代理 |
| 查分器凭据错误/权限不足 | 检查绑定的是导入Token/个人密钥，必要时重新生成；确认个人接口有写入权限 |
| 普通图片没有回复 | 被动模式的预期行为；用 `上传成绩` 附图获得可理解的错误提示 |
| 本地图片无法读取 | 检查接入端 get_image 返回形式、共享目录和明确白名单 |
| 图片过大/动画/识别超时 | 裁剪为只含一个二维码的清晰静态原图 |
| 无有效成绩 | 本次 Arcade 没有可上传记录或目标歌曲数据未能映射，不报告成功 |
| 正在上传/重复/限流 | 等待当前任务结束；5秒后用新消息重试；成功或结果不确定的同码等待120秒 |
| 提交超时/部分失败/结果不确定 | 先检查目标查分器；不要立即重试可能已成功的写入，稍后用新二维码人工决定 |
| 加密密钥未配置/解密失败 | 服务进程未加载正确环境；恢复原密钥，否则删除后重新绑定 |
| 旧处理器冲突 | 按第4节关闭旧上传入口并重启，勿同时提交 |
| 启动提示 Not found config of maimai_updata | 宿主尝试查找模块配置文件；本插件从环境读取配置，随后handlers加载成功即可，该提示本身不表示失败 |
| maimai-ffi无法导入 | 检查实际Python和CPU平台wheel；交付验证环境为Linux x86_64 Python3.10 |

普通图片也占用该用户默认5秒冷却，紧接发送的被动二维码可能安静忽略，等待5秒后重发。去重存内存且有时效，重启后会清空；部署为**单机器人进程**。多进程/多实例不共享锁，不支持同时用同一数据目录运行。

## 7. 数据、日志、备份与删除

数据库 `credentials.sqlite3` 按 QQ + 平台保存 Fernet 密文，密文中也绑定用户与平台；数据目录0700、数据库0600。无明文凭据内存缓存；只在单次操作栈内使用。SQLite开启 `secure_delete`，不保留 WAL；删除操作确实删除记录。备份或文件系统快照中的旧凭据无法由删除命令追溯擦除，撤销查分器凭据才会使旧副本失效。

机器人停止后备份数据库和加密密钥到分开控制权限的位置。**丢失密钥不能恢复已存凭据**；不要直接换密钥继续使用旧数据库。恢复需恢复匹配密钥；主动换钥时让用户先删除旧凭据再绑定，或另建空数据目录。

二维码和原始图片只在受限内存与子进程管道中处理，不写持久图片/二维码文件。日志只记录错误类型、配置冲突服务名等非敏感诊断信息，不记录事件、响应正文或traceback。

**但上游 NoneBot 1.8.0 在预处理器前以 INFO 记录原消息，可能包含二维码和凭据。** 管理员必须检查并过滤/关闭 `nonebot` 的原消息日志及 QQ 接入端日志、反向代理请求日志、调试追踪。插件不能保证整个机器人或 QQ 平台从不记录这些信息，也不能删除已发到群中的历史消息。凭据与二维码优先私聊，不要开启原消息 DEBUG 记录。

## 8. 更新、卸载与开发验收

更新：停机器人 → 备份仓库外数据库、密钥、原环境依赖列表 → 在插件目录 `git pull --ff-only`（或先审查新ZIP差异）→ 同一Python重新安装requirements并`pip check` → 阅读迁移说明 → 重启。不要覆盖自定义环境文件。未来上游API变化时应审查新的固定版本，不直接全局 `pip install -U`。

卸载：停机器人 → 从`MODULES_ON`删除`maimai_updata` → 删除插件目录 → 需要时撤销查分器Token → 根据保留需求删除仓库外数据与密钥及该服务配置 → 重启。不要盲目卸载共享的 aiohttp/Pillow 等 Hoshino 依赖。

开发测试：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m pip check
python -m compileall -q .
python -m pytest -q
```

复现真实宿主加载（隔离环境中执行）：

```bash
python -m pip install -r requirements-smoke.txt
python scripts/smoke_hoshino.py --hoshino-source /absolute/path/HoshinoBot
```

此脚本临时复制所给宿主源码，使用真实生命周期/事件分发/二维码解码，仅 QQ API 和成绩上传后端替换为测试对象；不会接入真实账户。`requirements-smoke.txt` 中绘图库仅用于已说明的隔离测试，不要求更新现有机器人绘图库。

最小真实验收：管理员先检查日志与接入端 → 私聊绑定自己的一个目标 → `上传配置` → 用刚生成的真实文本码上传一次 → 登陆所选平台核对记录 → 获取另一张新二维码直接发图再次核对 → 用同样方式验证另一目标 → 在专门测试群只启用主服务验证显式上传，再启用自动服务验证裸图 → 禁用服务确认不扫描。普通照片应安静；无效显式图应提示；多码应拒绝；再发送同一消息不会重复提交。不要将真实Token、二维码截图、原消息日志放入Issue、CI或公开仓库。

本项目新代码采用 GPL-3.0（见 LICENSE），与宿主许可保持兼容；第三方许可与来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
