"""Application acceptance with actual encrypted storage, no live accounts."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet

from maimai_updata.app import Application, PRIVATE_WARNING, TTLCache, _message_parts
from maimai_updata.config import Config
from maimai_updata.core.image_fetch import ImageError
from maimai_updata.core.uploader import UploadError
from maimai_updata.database import Database


CODE = "SGWCMAID-unit-test-account-A"
OTHER_CODE = "SGWCMAID-unit-test-account-B"


def event(text="", images=(), uid="10001", message_id=1, private=True):
    segments = [{"type": "text", "data": {"text": text}}] if text else []
    segments.extend({"type": "image", "data": image} for image in images)
    return {"user_id": int(uid), "message_id": message_id, "self_id": 999,
            "message_type": "private" if private else "group", "group_id": None if private else 123,
            "message": segments}


@pytest.fixture
def app(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", encryption_key=Fernet.generate_key().decode())
    database = Database(cfg.data_dir, cfg.encryption_key)
    uploader = SimpleNamespace(upload=AsyncMock(return_value=SimpleNamespace(message="confirmed-test-upload")))
    fetcher = SimpleNamespace(fetch=AsyncMock(return_value=b"fake-image-decoded-by-test"))
    decoder = AsyncMock(return_value=[CODE])
    application = Application(cfg, database=database, uploader=uploader, fetcher=fetcher, decoder=decoder)
    # A controllable clock makes finite cooldown/dedup behavior deterministic.
    application.test_clock = [1000.0]
    for cache in (application.messages, application.codes, application.cooldowns):
        cache.clock = lambda: application.test_clock[0]
    return application


def bind(app, uid="10001", target="divingfish"):
    app._database.bind(uid, target, "unit-test-" + target + "-" + uid)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["command_text", "bare_text", "passive_image", "command_image"])
async def test_all_entry_points_use_same_uploader(app, mode):
    bind(app)
    messages = {
        "command_text": event("上传成绩  " + CODE + "  "),
        "bare_text": event(CODE),
        "passive_image": event(images=[{"file": "test.image"}]),
        "command_image": event("上传成绩", images=[{"url": "https://example.invalid/test.png"}]),
    }
    assert await app.handle(None, messages[mode]) == "confirmed-test-upload"
    app.uploader.upload.assert_awaited_once_with(CODE, "divingfish", "unit-test-divingfish-10001")


@pytest.mark.asyncio
async def test_source_selection_never_falls_back_to_other_bound_source(app):
    bind(app)
    reply = await app.handle(None, event("上传源 落雪"))
    assert "尚未绑定" in reply and "私聊" in reply
    assert app._database.get_target("10001") == "lxns"
    reply = await app.handle(None, event("上传成绩 " + CODE, message_id=2))
    assert "落雪" in reply and "尚未绑定" in reply
    app.uploader.upload.assert_not_awaited()
    assert "已加密保存" in await app.handle(None, event("落雪个人密钥 test-only-lxns"))
    app.test_clock[0] += 6
    assert await app.handle(None, event("上传成绩 " + CODE, message_id=3)) == "confirmed-test-upload"
    app.uploader.upload.assert_awaited_once_with(CODE, "lxns", "test-only-lxns")


@pytest.mark.asyncio
@pytest.mark.parametrize("command,target", [("水鱼导入token", "divingfish"), ("落雪个人密钥", "lxns")])
async def test_binding_in_groups_does_not_store_or_echo_secret(app, command, target):
    secret = "SYNTHETIC-test-private-only"
    reply = await app.handle(None, event(command + " " + secret, private=False))
    assert reply == PRIVATE_WARNING
    assert secret not in reply
    assert app._database.get_secret("10001", target) is None


@pytest.mark.asyncio
async def test_config_view_and_deletion_clear_only_owners_caches(app):
    bind(app)
    bind(app, target="lxns")
    bind(app, uid="10002")
    for cache in (app.messages, app.codes):
        cache.put(("10001", "fixture"), 120)
        cache.put(("10002", "fixture"), 120)
    app.cooldowns.put("10001", 120)
    reply = await app.handle(None, event("上传配置"))
    assert "水鱼：已绑定" in reply and "落雪：已绑定" in reply
    assert "unit-test" not in reply
    assert "水鱼" in await app.handle(None, event("删除水鱼token"))
    assert app._database.status("10001") == {"lxns"}
    for cache in (app.messages, app.codes):
        assert not cache.has(("10001", "fixture"))
        assert cache.has(("10002", "fixture"))
    assert not app.cooldowns.has("10001")
    assert "全部上传" in await app.handle(None, event("删除上传凭据"))
    assert app._database.status("10001") == set()
    assert app._database.status("10002") == {"divingfish"}


@pytest.mark.asyncio
async def test_ordinary_and_broken_passive_images_are_silent(app):
    app.decoder.return_value = []
    assert await app.handle(None, event(images=[{"file": "ordinary.image"}])) is None
    app.test_clock[0] += 6
    app.fetcher.fetch.side_effect = ImageError("decode", "图片无法识别。")
    assert await app.handle(None, event(images=[{"file": "corrupt.image"}], message_id=2)) is None
    app.uploader.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_explicit_invalid_image_provides_readable_error(app):
    app.decoder.return_value = []
    reply = await app.handle(None, event("上传成绩", images=[{"file": "ordinary.image"}]))
    assert "未识别到有效舞萌二维码" in reply
    app.uploader.upload.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("auto_images,auto_allowed", [(False, True), (True, False)])
async def test_auto_image_switches_do_not_block_explicit_upload(app, auto_images, auto_allowed):
    bind(app)
    app.config.auto_images = auto_images
    image_event = event(images=[{"file": "test.image"}])
    assert await app.handle(None, image_event, auto_allowed=auto_allowed) is None
    app.fetcher.fetch.assert_not_awaited()
    assert await app.handle(None, event("上传成绩", images=[{"file": "test.image"}], message_id=2), auto_allowed=auto_allowed) == "confirmed-test-upload"


@pytest.mark.asyncio
async def test_bare_code_switch_and_custom_prefix(app):
    bind(app)
    app.config.allow_bare_codes = False
    app.config.upload_command = "我的成绩上传"
    assert await app.handle(None, event(CODE)) is None
    assert await app.handle(None, event("上传成绩 " + CODE)) is None
    assert await app.handle(None, event("我的成绩上传 " + CODE)) == "confirmed-test-upload"
    assert "我的成绩上传" in app.help()


@pytest.mark.asyncio
@pytest.mark.parametrize("input_kind", ["text", "image", "both"])
async def test_distinct_codes_never_choose_an_account(app, input_kind):
    bind(app)
    app.decoder.return_value = [OTHER_CODE] if input_kind == "both" else [CODE, OTHER_CODE]
    if input_kind == "text":
        message = event("上传成绩 " + CODE + " " + OTHER_CODE)
    elif input_kind == "image":
        message = event(images=[{"file": "test.image"}])
    else:
        message = event("上传成绩 " + CODE, images=[{"file": "test.image"}])
    assert "多个不同" in await app.handle(None, message)
    app.uploader.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_multiple_images_same_code_upload_once_but_limits_apply(app):
    bind(app)
    images = [{"file": "test.image"}] * 3
    assert await app.handle(None, event("上传成绩", images=images)) == "confirmed-test-upload"
    assert app.fetcher.fetch.await_count == 3
    assert app.uploader.upload.await_count == 1
    app.test_clock[0] += 6
    assert "一次最多处理 3 张" in await app.handle(None, event("上传成绩", images=images + images, message_id=2))
    assert app.fetcher.fetch.await_count == 3
    app.test_clock[0] += 6
    assert await app.handle(None, event(images=images + images, message_id=3)) is None


@pytest.mark.asyncio
async def test_incomplete_multi_image_scan_never_selects_first_code(app):
    bind(app)
    app.fetcher.fetch.side_effect = [b"image-1", ImageError("timeout", "下载图片超时。")]
    assert "超时" in await app.handle(None, event("上传成绩", images=[{"file": "first"}, {"file": "second"}]))
    app.uploader.upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_user_busy_and_global_concurrency_are_bounded(app):
    app.slots = asyncio.Semaphore(1)
    bind(app)
    bind(app, "10002")
    started, release = asyncio.Event(), asyncio.Event()
    async def blocked(*args):
        started.set()
        await release.wait()
        return SimpleNamespace(message="confirmed-test-upload")
    app.uploader.upload.side_effect = blocked
    first = asyncio.create_task(app.handle(None, event("上传成绩 " + CODE)))
    await started.wait()
    assert "正在处理" in await app.handle(None, event("上传成绩 " + OTHER_CODE, message_id=2))
    assert "任务已满" in await app.handle(None, event("上传成绩 " + OTHER_CODE, uid="10002"))
    assert await app.handle(None, event(images=[{"file": "test.image"}], message_id=3)) is None
    release.set()
    assert await first == "confirmed-test-upload"
    assert not app.busy and not app.active_codes and not app.slots.locked()
    assert app.uploader.upload.await_count == 1


@pytest.mark.asyncio
async def test_duplicate_message_and_qr_expire(app):
    bind(app)
    message = event("上传成绩 " + CODE)
    await app.handle(None, message)
    app.test_clock[0] += 6
    assert "重复消息" in await app.handle(None, message)
    assert "近期已提交" in await app.handle(None, event("上传成绩 " + CODE, message_id=2))
    assert app.uploader.upload.await_count == 1
    app.test_clock[0] += 121
    assert await app.handle(None, message) == "confirmed-test-upload"
    assert app.uploader.upload.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("uncertain", [False, True])
async def test_failed_upload_releases_state_and_retry_policy(app, uncertain):
    bind(app)
    app.uploader.upload.side_effect = [UploadError("timeout", "safe-timeout-message", uncertain), SimpleNamespace(message="confirmed-test-upload")]
    assert await app.handle(None, event("上传成绩 " + CODE)) == "safe-timeout-message"
    assert not app.busy and not app.active_codes and not app.slots.locked()
    app.test_clock[0] += 6
    reply = await app.handle(None, event("上传成绩 " + CODE, message_id=2))
    if uncertain:
        assert "近期已提交" in reply
        assert app.uploader.upload.await_count == 1
        app.test_clock[0] += 121
        reply = await app.handle(None, event("上传成绩 " + CODE, message_id=3))
    assert reply == "confirmed-test-upload"


@pytest.mark.asyncio
async def test_cancellation_releases_task_state(app):
    bind(app)
    started = asyncio.Event()
    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()
    app.uploader.upload.side_effect = blocked
    task = asyncio.create_task(app.handle(None, event("上传成绩 " + CODE)))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not app.busy and not app.active_codes and not app.slots.locked()


@pytest.mark.asyncio
async def test_unexpected_exceptions_do_not_leak_sensitive_values(app, caplog):
    bind(app)
    secret = "SYNTHETIC-SECRET-MUST-NOT-APPEAR"
    app.uploader.upload.side_effect = RuntimeError(secret + CODE)
    reply = await app.handle(None, event("上传成绩 " + CODE))
    assert "处理失败" in reply
    assert secret not in reply + caplog.text and CODE not in reply + caplog.text
    assert not app.busy and not app.active_codes


def test_onebot_message_objects_and_raw_cq_image_segments():
    from aiocqhttp.message import Message
    original = event()
    original["message"] = Message("上传成绩 [CQ:image,file=test.image,url=https://example.invalid/test.png]")
    text, images = _message_parts(original)
    assert text == "上传成绩"
    assert images[0]["file"] == "test.image"
    original["message"] = str(original["message"])
    assert _message_parts(original) == (text, images)


def test_ttl_cache_has_bounded_storage_and_user_isolation():
    clock = [1]
    cache = TTLCache(maximum=2, clock=lambda: clock[0])
    cache.put(("10001", "a"), 10)
    cache.put(("10002", "b"), 10)
    cache.put(("10001", "c"), 10)
    assert not cache.has(("10001", "a"))
    cache.clear_user("10001")
    assert cache.has(("10002", "b"))
    clock[0] += 11
    assert not cache.has(("10002", "b"))
