"""NoneBot 1 / aiocqhttp integration; no NoneBot 2 dependencies."""
import logging
import time
from collections import OrderedDict


LOGGER = logging.getLogger("maimai-upload")
SERVICE_NAME = "maimai-upload"
AUTO_SERVICE_NAME = "maimai-upload-auto"
PRIVATE_BINDING_WARNING = (
    "上传凭据只能私聊绑定；请添加机器人好友后私聊。"
    "群里已经发出的凭据可能已泄露，请到查分器撤销或更换。"
)
_registration = None


def plain_text(event):
    """Read actual OneBot text segments without expanding image/file values."""
    message = event.get("message", ())
    if isinstance(message, str):
        return message.strip()
    chunks = []
    for segment in message:
        if isinstance(segment, dict):
            kind, data = segment.get("type"), segment.get("data", {})
        else:
            kind, data = getattr(segment, "type", None), getattr(segment, "data", {})
        if kind == "text" and isinstance(data.get("text"), str):
            chunks.append(data["text"])
    return "".join(chunks).strip()


def managed_prefixes(config):
    return (
        config.upload_command, "SGWCMAID", "水鱼导入token", "水鱼导入Token",
        "落雪个人密钥", "上传源", "删除上传凭据", "删除水鱼token",
        "删除落雪密钥", "上传配置", "舞萌上传帮助",
    )


def conflicting_services(trigger, config, event=None):
    """Inspect the real Hoshino prefix registry, including later-loaded modules.

    Do not try to cancel another NoneBot preprocessor: those run concurrently.
    The installed maimaiDX upload module is also recognized by module name.
    """
    conflicts = set()
    prefixes = managed_prefixes(config)
    for prefix, service_functions in trigger.prefix.trie.items():
        for service_function in service_functions:
            service = service_function.sv
            if service.name in (SERVICE_NAME, AUTO_SERVICE_NAME):
                continue
            module = getattr(service_function.func, "__module__", "")
            overlaps = any(prefix.startswith(value) or value.startswith(prefix)
                           for value in prefixes)
            if not (overlaps or module.endswith(".commands.mai_upload")):
                continue
            if event is not None and not service._check_all(event):
                continue
            conflicts.add(service.name)
    return tuple(sorted(conflicts))


class Router:
    def __init__(self, config, application, main_service, auto_service, privilege,
                 trigger, clock=time.monotonic):
        self.config = config
        self.application = application
        self.main_service = main_service
        self.auto_service = auto_service
        self.privilege = privilege
        self.trigger = trigger
        self.clock = clock
        self._conflict_notices = OrderedDict()

    def _explicit(self, event):
        return plain_text(event).startswith(managed_prefixes(self.config))

    async def _send(self, bot, event, reply):
        if reply is None:
            return
        try:
            await bot.send(event, reply)
        except Exception as error:
            # Exceptions from adapters may contain API arguments, so log type only.
            LOGGER.warning("Sending upload response failed: %s", type(error).__name__)

    async def _dispatch(self, bot, event, auto_allowed):
        try:
            reply = await self.application.handle(bot, event, auto_allowed=auto_allowed)
        except Exception as error:
            LOGGER.error("Upload handler failed: %s", type(error).__name__)
            reply = ("成绩上传服务发生内部错误，请联系管理员检查配置。"
                     if self._explicit(event) else None)
        await self._send(bot, event, reply)

    async def group(self, bot, event):
        if event.get("message_type") != "group" or event.get("anonymous"):
            return
        # A mistaken public secret deserves this warning even when uploads are
        # disabled. This text-only guard never scans pictures or opens storage.
        if plain_text(event).lower().startswith(("水鱼导入token", "落雪个人密钥")):
            blocked_group = getattr(self.privilege, "check_block_group", lambda _: False)
            if (not self.privilege.check_block_user(event.get("user_id"))
                    and not blocked_group(event.get("group_id"))):
                await self._send(bot, event, PRIVATE_BINDING_WARNING)
            return
        if not self.main_service._check_all(event):
            return
        try:
            conflicts = conflicting_services(self.trigger, self.config, event)
        except Exception as error:
            LOGGER.error("Upload conflict check failed: %s", type(error).__name__)
            # Unknown registry shape must not accidentally submit twice.
            conflicts = ("unknown",)
        if conflicts:
            if self._explicit(event):
                now, group_id = self.clock(), event.get("group_id")
                last = self._conflict_notices.get(group_id)
                if last is None or now - last >= 60:
                    self._conflict_notices[group_id] = now
                    self._conflict_notices.move_to_end(group_id)
                    while len(self._conflict_notices) > 256:
                        self._conflict_notices.popitem(last=False)
                    await self._send(
                        bot, event,
                        "本群存在已启用的旧上传或同名命令处理器，本插件已停止处理本次请求。"
                        "请管理员按 README 关闭旧上传处理器后重启；本插件仍可在私聊中使用。"
                    )
            return
        auto_allowed = (self.config.auto_images and self.auto_service._check_all(event))
        await self._dispatch(bot, event, auto_allowed=auto_allowed)

    async def private(self, bot, event):
        if event.get("message_type") != "private":
            return
        # hoshino.priv.check_priv explicitly rejects every private event.
        # Honor its blacklist directly while permitting each user's own binding.
        if self.privilege.check_block_user(event.get("user_id")):
            return
        await self._dispatch(bot, event, auto_allowed=self.config.auto_images)


def setup():
    """Register once after Hoshino has initialized its actual NoneBot 1 instance."""
    global _registration
    if _registration is not None:
        return _registration

    import hoshino
    import nonebot
    from hoshino import Service, priv, trigger
    from .app import Application
    from .config import Config

    config = Config.from_env()
    main_service = Service(
        SERVICE_NAME, manage_priv=priv.ADMIN, enable_on_default=False,
        help_="私聊发送 舞萌上传帮助；本群启用后支持上传成绩。",
    )
    auto_service = Service(
        AUTO_SERVICE_NAME, manage_priv=priv.ADMIN, enable_on_default=False,
        help_="需同时启用 maimai-upload，允许自动识别群内舞萌二维码图片。",
    )
    application = Application(config)
    router = Router(config, application, main_service, auto_service, priv, trigger)
    bot = hoshino.get_bot()

    @bot.on_message("group")
    async def group_message(event):
        await router.group(bot, event)

    @bot.on_message("private")
    async def private_message(event):
        await router.private(bot, event)

    @nonebot.on_startup
    async def check_conflicts():
        conflicts = conflicting_services(trigger, config)
        if conflicts:
            LOGGER.warning(
                "Upload command conflict with services: %s. "
                "Plugin group processing is disabled wherever a conflicting "
                "service is enabled. Disable its old upload module and restart.",
                ", ".join(conflicts),
            )

    @bot.server_app.after_serving
    async def close_application():
        close = getattr(application, "close", None)
        if close is not None:
            await close()

    _registration = router
    return router


# Hoshino's real load_plugins() discovers .py files inside this module directory.
# This is deliberately inert when imported by tests or standalone tooling.
if __name__.startswith("hoshino.modules."):
    setup()
