# maimai-py 接口核验记录

核验日期：2026-09-21。这里记录本次实际取得的 Git 源码、PyPI wheel 和官方服务端代码；未把前一会话的结论作为证据。

## 取得的版本

| 对象 | 实际结果 |
| --- | --- |
| `AFKsuper/maimai.py` | `git ls-remote --symref` 和 shallow clone 成功；默认分支 `main`；HEAD `9a02bc6f9026d4af238ace3fabe9fc399cfa5367`，提交日期 2026-06-11 |
| 该 fork 的 `pyproject.toml` | 版本 `1.5.1`；Python `^3.9`；`maimai-ffi==0.7.0`；`httpx ^0.28.0`；`httpcore ^1.0.9`；`aiocache ^0.12.3`；`tenacity ^9.1.2` |
| 实际选用的 PyPI 发行包 | `maimai-py==1.5.2`；METADATA 声明 Python `>=3.9,<4.0`、`maimai-ffi==0.7.1` |
| 实际安装验证 | CPython `3.10.21`，Linux x86_64，maimai-py `1.5.2`，maimai-ffi `0.7.1`，httpx `0.28.1`，httpcore `1.0.9`，aiocache `0.12.3`，tenacity `9.1.4` |
| 水鱼官方服务端 | 额外读取 `Diving-Fish/maimaidx-prober` 的 `e01075f70bb8dc1368ecbc2502a38edae525893c`（2026-09-17），核对上传确认、计数和旧成绩覆盖行为 |

1.5.1 与 1.5.2 的 `providers/lxns.py` 有实际差异：1.5.2 的 `_ser_score` 增加 `songs` 参数并过滤未找到/停用歌曲；个人密钥的 401 改判为玩家凭据异常；其余客户端调用协议相同。因此选用并固定 1.5.2，插件拒绝未审查的其他版本，不能把该 fork 的 1.5.1 误称为 PyPI 1.5.2。

maimai-ffi 是编译分发的组件。本次在 Python 3.10 与当前主运行时 Python 3.12 上均取得可导入的 Linux x86_64 wheel；这不证明所有操作系统/架构均有 wheel。插件支持矩阵以 README 的已测环境为准。

## 真实接口及复用方式

源文件为发行包的 `maimai_py/maimai.py`、`models.py`、`providers/arcade.py`、`providers/divingfish.py`、`providers/lxns.py`、`exceptions.py`。对应 fork 可读源码见 [maimai.py 固定提交](https://github.com/AFKsuper/maimai.py/tree/9a02bc6f9026d4af238ace3fabe9fc399cfa5367)。发行包见 [PyPI 1.5.2](https://pypi.org/project/maimai-py/1.5.2/)。

真实导出包括 `MaimaiClient`、`MaimaiClientMultithreading`、`PlayerIdentifier`、`ArcadeProvider`、`DivingFishProvider`、`LXNSProvider`。

`MaimaiClient` 有 singleton 行为，且重复初始化可能替换 HTTP 会话。本插件选择其公开导出的非 singleton 版本 `MaimaiClientMultithreading(timeout=..., trust_env=False, follow_redirects=False)`，每次上传创建独立实例。该版本没有公共 `aclose` / async context manager；插件在 `finally` 关闭 `client._client` 和 `client._cache`，这些私有接口由固定依赖和真实包测试约束。

共用上传逻辑直接调用：

1. `ArcadeProvider(http_proxy=...).get_identifier(code, client)`，内部调用 `maimai_ffi.arcade.get_uid_encrypted(code, http_proxy=...)`，返回 `PlayerIdentifier(credentials=加密标识)`。
2. `ArcadeProvider.get_scores_all(identifier, client)`，内部调用 `get_user_scores(identifier.credentials.encode(), http_proxy=...)`，经过真实歌曲数据映射后返回 `list[Score]`。没有手写舞萌机台 HTTP 接口。
3. 当前目标 provider 的 `get_scores_all(PlayerIdentifier(credentials=个人凭据), client)`，只读取这份凭据所属的目标账户，保留已有 FC/FS、较高达成率和 DX 分，读取失败就停止上传。
4. 当前目标 provider 的 `update_scores(identifier, scores, client)` 原始方法体。上游在这个方法上装饰了 `tenacity` 的 `RequestError` 重试三次；插件通过固定版本方法的 `__wrapped__` 绕过此重试，每次只允许一个上传 POST。只读获取仍保留上游重试，总流程另有总超时。

也核验了公开封装 `client.qrcode(qrcode, http_proxy=None)`、`client.scores(identifier, provider)`、`client.updates(identifier, scores, provider)`；其中 `scores` 返回 `MaimaiScores`，实际列表在 `.scores`。插件直接使用 provider 以避免上传之外的 B50 分组工作。

### 二维码规则

上游公开说明只规定以 **SGWCMAID** 开头，没有公开固定总长度或完整字符表；ArcadeProvider 将字符串直接传给编译分发的 FFI 校验。插件只做完整候选、非空后缀、空白分隔和控制字符检查；4096 UTF-8 字节是资源限制，不是伪造的业务长度规则。真正的有效性、过期和拒绝由上游确认。不会把“前缀符合”当成真实账户验证成功。

### 水鱼凭据与确认

`DivingFishProvider(developer_token=...)` 的开发者 Token 用于开发者查询接口；**不是用户上传所需的 Import-Token**。个人上传采用 `PlayerIdentifier(credentials=import_token)`，不提供 `username`，真实请求头为 `Import-Token`，路径为 `/api/maimaidxprober/player/update_records`。若同时给 `username`，上游会把 credentials 当密码走登录，因此插件不这样使用。不需要额外 QQ 或用户名绑定。

[官方服务端固定代码](https://github.com/Diving-Fish/maimaidx-prober/blob/e01075f70bb8dc1368ecbc2502a38edae525893c/database/routes/maimai.py) 中的 `update_records` 返回 `message: 更新成功`、`updates`、`creates`。插件检查 HTTP 状态、成功消息、非负整数计数，并核对 `updates + creates` 与真实提交条目数。不匹配则提示部分失败或结果异常。不会只因 HTTP 200 就声称全部成功。

同一个服务端方法会用提交值覆盖已有 FC/FS；Arcade 数据中的 FC/FS 是 `None`。所以本插件上传前读取同账户已有成绩并合并，避免清空状态。不提供绕过该保护读取的开关。调用时已有成绩被其他客户端并发更新仍存在平台 API 自身无事务比较更新接口带来的竞态；不要同时运行多个上传器。

官方文档路径在本次实际仓库中已移动至 [doc/docs/developer/zh-api-document.md](https://github.com/Diving-Fish/maimaidx-prober/blob/e01075f70bb8dc1368ecbc2502a38edae525893c/doc/docs/developer/zh-api-document.md)，旧 `database/zh-api-document.md` 链接返回 404。水鱼个人资料页生成的 Import-Token 与开发者 Token/OAuth Bearer 不应混用。

### 落雪凭据与确认

`LXNSProvider(developer_token=...)` 用于开发者级接口。个人密钥通过 `PlayerIdentifier(credentials=key)` 提供，真实个人端点为 `/api/v0/user/maimai/player/scores`；普通密钥使用 `X-User-Token`，上游识别为 JWT 的凭据使用 `Authorization: Bearer ...`。不需要开发者 Token、好友码或额外 QQ 参数。

上游 1.5.2 对某些 HTTP 200 + `success:false` 的未知错误码可能直接返回，本插件额外严格检查 `success is True` 和成功业务码；显式部分失败也不会报告全部成功。落雪只确认请求成功、没有逐条入库计数时，回复明确写“本次提交 N 条，平台未返回逐条入库数量”。这个 N 是实际序列化并提交的条目数，不是编造的入库数量。

上游 [LXNSProvider 文档](https://github.com/AFKsuper/maimai.py/blob/9a02bc6f9026d4af238ace3fabe9fc399cfa5367/docs/providers/lxns.md) 提醒新用户可能需先用落雪官方上传方式初始化账户，隐私配置也会限制接口访问。插件提示检查账户初始化和密钥权限，不会用另一个平台作为暗中回退。

### 数据与错误限制

上游 [Arcade 文档](https://github.com/AFKsuper/maimai.py/blob/9a02bc6f9026d4af238ace3fabe9fc399cfa5367/docs/providers/arcade.md) 明确 1.53+ 只能取得部分成绩数据，主要为达成率和 DX 分，不能取得新的 FC/FS/游玩次数等完整信息。插件只能保留查分器已有状态，不能恢复上游不给的数据。

核验并处理的异常包括 `AimeServerError`、`ArcadeIdentifierError`、`TitleServerBlockedError`、`TitleServerNetworkError`、`InvalidPlayerIdentifierError`、`InvalidDeveloperTokenError`、`PrivacyLimitationError`、httpx/httpcore 网络及超时异常。上游错误消息有可能包含响应正文或请求信息；插件不回显异常文本，不保存 QR/加密玩家标识。上传发出后超时/断连/结果不明会标记为不确定，交给上层短时去重，提示用户先检查查分器而不是立即自动重发。

## 许可证核对

该 fork 的 pyproject 及 PyPI METADATA 声明 MIT，但仓库 `LICENSE` 和 1.5.2 wheel 内 `licenses/LICENSE` 实际为 **Apache-2.0** 文本，存在上游元数据不一致。maimai-ffi 0.7.1 wheel 附带 MIT 文本，copyright 2024 Usagi no Niku。插件没有复制或打包这些库的源码/二进制，由 pip 安装原发行包，保留发行包自带许可；本项目许可不替代它们的许可。maimai-ffi 对外提供编译接口，不宣称其内部协议源码已经审查。

## 测试边界

`tests/test_uploader.py` 使用已安装的真正 maimai-py 1.5.2 providers、FFI 包的函数位置、真实 HTTPX 构造和真实成绩序列化；只把 FFI 网络调用与 HTTP transport 替换为合成 fixture。测试覆盖两个平台的参数、个人凭据头、FC/FS 保留、上传仅一次、200 假失败、部分失败、超时及会话关闭。`tests/test_parser.py` 覆盖空白、无效前缀、多账户、控制字符与安全大小边界。

这些测试证明当前安装包的 API 兼容性与本地行为，不等于真实舞萌服务器或真实查分器账号验收。本次没有真实用户二维码、个人凭据或运行中的 QQ 接入端，因此没有声称完成真实账户上传。真实最小验收按 README 执行。
