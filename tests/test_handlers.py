import asyncio
from types import SimpleNamespace

from maimai_updata.handlers import Router, conflicting_services, plain_text


def run(coro):
    return asyncio.run(coro)


class FakeService:
    def __init__(self, name, groups=()):
        self.name = name
        self.groups = set(groups)

    def _check_all(self, event):
        return event.get("group_id") in self.groups and event.get("user_id") != 999


class FakeApplication:
    def __init__(self, reply="handled"):
        self.calls = []
        self.reply = reply

    async def handle(self, bot, event, *, auto_allowed):
        self.calls.append((event, auto_allowed))
        return self.reply


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send(self, event, text):
        self.messages.append((event, text))


def event(text="", kind="group", group_id=10, user_id=100):
    result = {
        "message_type": kind, "message": [{"type": "text", "data": {"text": text}}],
        "user_id": user_id, "message_id": 101,
    }
    if kind == "group":
        result["group_id"] = group_id
    return result


def make_router(reply="handled", auto=True, main_groups=(10,), auto_groups=()):
    config = SimpleNamespace(auto_images=auto, upload_command="上传成绩")
    application = FakeApplication(reply)
    main = FakeService("maimai-upload", main_groups)
    automatic = FakeService("maimai-upload-auto", auto_groups)
    privilege = SimpleNamespace(check_block_user=lambda user: user == 999)
    trigger = SimpleNamespace(prefix=SimpleNamespace(trie={}))
    return Router(config, application, main, automatic, privilege, trigger), FakeBot()


def test_disabled_group_never_calls_application_or_decodes_images():
    router, bot = make_router(main_groups=())
    run(router.group(bot, event("上传成绩 SGWCMAIDTEST")))
    assert router.application.calls == []
    assert bot.messages == []


def test_group_binding_only_warns_without_application_even_when_disabled():
    for groups in [(), (10,)]:
        router, bot = make_router(main_groups=groups)
        run(router.group(bot, event("水鱼导入Token DO_NOT_ECHO")))
        assert router.application.calls == []
        assert len(bot.messages) == 1
        assert "私聊" in bot.messages[0][1] and "撤销或更换" in bot.messages[0][1]
        assert "DO_NOT_ECHO" not in bot.messages[0][1]


def test_explicit_upload_in_enabled_group_without_auto_service():
    router, bot = make_router()
    run(router.group(bot, event("上传成绩 SGWCMAIDTEST")))
    assert len(router.application.calls) == 1
    assert router.application.calls[0][1] is False
    assert bot.messages[0][1] == "handled"


def test_auto_recognition_requires_both_services_and_config():
    for configured, groups, expected in [(True, (10,), True), (False, (10,), False), (True, (), False)]:
        router, bot = make_router(auto=configured, auto_groups=groups)
        run(router.group(bot, event()))
        assert router.application.calls[0][1] is expected


def test_private_uses_separate_path_and_blacklist():
    router, bot = make_router(main_groups=())
    run(router.private(bot, event("水鱼导入token FAKE", kind="private")))
    assert len(router.application.calls) == 1
    assert router.application.calls[0][1] is True
    run(router.private(bot, event("上传成绩 SGWCMAIDTEST", kind="private", user_id=999)))
    assert len(router.application.calls) == 1


def test_no_reply_for_passive_ordinary_image():
    router, bot = make_router(reply=None, auto_groups=(10,))
    incoming = event()
    incoming["message"] = [{"type": "image", "data": {"file": "opaque-image-id"}}]
    run(router.group(bot, incoming))
    assert len(router.application.calls) == 1
    assert bot.messages == []


def test_ordinary_messages_are_silent_when_legacy_conflicts():
    router, bot = make_router()
    service = FakeService("maimaiDX", (10,))
    handler = SimpleNamespace(sv=service, func=lambda: None)
    router.trigger.prefix.trie["上传成绩"] = [handler]
    run(router.group(bot, event()))
    assert router.application.calls == []
    assert bot.messages == []


def test_legacy_conflict_is_dynamic_and_fails_closed_with_rate_limited_notice():
    router, bot = make_router()
    service = FakeService("maimaiDX", (10,))
    handler = SimpleNamespace(sv=service, func=lambda: None)
    incoming = event("上传成绩 SGWCMAIDSECRET")
    assert conflicting_services(router.trigger, router.config, incoming) == ()
    # Simulate maimaiDX being loaded after this plugin.
    router.trigger.prefix.trie["上传成绩"] = [handler]
    run(router.group(bot, incoming))
    run(router.group(bot, incoming))
    assert router.application.calls == []
    assert len(bot.messages) == 1
    assert "SGWCMAIDSECRET" not in bot.messages[0][1]
    # Disabling the old service makes this plugin usable without touching its code.
    service.groups.clear()
    run(router.group(bot, incoming))
    assert len(router.application.calls) == 1


def test_private_is_not_blocked_by_group_only_legacy_prefixes():
    router, bot = make_router()
    router.trigger.prefix.trie["水鱼导入token"] = [
        SimpleNamespace(sv=FakeService("maimaiDX", (10,)), func=lambda: None)
    ]
    run(router.private(bot, event("水鱼导入token TEST", kind="private")))
    assert len(router.application.calls) == 1


def test_conflict_detects_shorter_prefix_and_group_permissions():
    router, _ = make_router()
    router.trigger.prefix.trie["上传"] = [
        SimpleNamespace(sv=FakeService("old", (10,)), func=lambda: None)
    ]
    assert conflicting_services(router.trigger, router.config, event()) == ("old",)
    assert conflicting_services(router.trigger, router.config, event(group_id=11)) == ()


def test_private_global_auto_switch_off():
    router, bot = make_router(auto=False)
    run(router.private(bot, event(kind="private")))
    assert router.application.calls[0][1] is False


def test_anonymous_and_blocked_group_user_are_ignored():
    router, bot = make_router()
    incoming = event()
    incoming["anonymous"] = {"id": 1}
    run(router.group(bot, incoming))
    run(router.group(bot, event(user_id=999)))
    assert router.application.calls == []


def test_exception_content_is_not_logged_or_replied(caplog):
    router, bot = make_router()

    async def broken(*args, **kwargs):
        raise RuntimeError("SECRET_TOKEN_AND_QRCODE")

    router.application.handle = broken
    run(router.group(bot, event("上传成绩 SGWCMAIDTEST")))
    assert "SECRET_TOKEN_AND_QRCODE" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "SECRET_TOKEN_AND_QRCODE" not in bot.messages[0][1]


def test_segment_objects_and_dicts_extract_only_text():
    incoming = event()
    incoming["message"] = [
        SimpleNamespace(type="text", data={"text": " 上传成绩 "}),
        {"type": "image", "data": {"file": "DO_NOT_EXPAND", "url": "SECRET_URL"}},
    ]
    assert plain_text(incoming) == "上传成绩"
