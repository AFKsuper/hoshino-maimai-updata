import asyncio
import base64
import io
import socket
from unittest.mock import AsyncMock

import aiohttp
import pytest
import qrcode
from PIL import Image

from maimai_updata.core.image_fetch import (
    ImageError, ImageFetcher, ImageLimits, PublicResolver, validate_image_url,
)
from maimai_updata.core.qr import decode_qr_codes


def png_bytes(size=(100, 100)):
    output = io.BytesIO()
    Image.new("RGB", size, "white").save(output, format="PNG")
    return output.getvalue()


def qr_bytes(value="SGWCMAID-test-only-no-real-account"):
    output = io.BytesIO()
    qrcode.make(value).save(output, format="PNG")
    return output.getvalue()


@pytest.mark.asyncio
async def test_real_qr_subprocess_and_ordinary_image():
    value = "SGWCMAID-test-only-no-real-account"
    assert await decode_qr_codes(qr_bytes(value)) == [value]
    assert await decode_qr_codes(png_bytes()) == []


@pytest.mark.asyncio
async def test_multiple_distinct_qrs_are_all_returned():
    first = qrcode.make("SGWCMAID-test-account-A").convert("RGB")
    second = qrcode.make("SGWCMAID-test-account-B").convert("RGB")
    canvas = Image.new("RGB", (first.width + second.width + 80, max(first.height, second.height) + 80), "white")
    canvas.paste(first, (20, 20))
    canvas.paste(second, (first.width + 60, 20))
    output = io.BytesIO()
    canvas.save(output, format="PNG")
    assert set(await decode_qr_codes(output.getvalue())) == {"SGWCMAID-test-account-A", "SGWCMAID-test-account-B"}


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,limits,code", [
    (b"not an image", ImageLimits(), "decode"),
    (b"", ImageLimits(), "empty"),
    (b"1234", ImageLimits(max_bytes=3), "too_large"),
    (png_bytes((50, 50)), ImageLimits(max_pixels=1000), "pixels"),
])
async def test_bad_or_oversized_image(raw, limits, code):
    with pytest.raises(ImageError) as caught:
        await decode_qr_codes(raw, limits)
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_decode_timeout_kills_and_reaps_child(monkeypatch):
    import maimai_updata.core.qr as module
    real_create = asyncio.create_subprocess_exec
    children = []

    async def tracked(*args, **kwargs):
        process = await real_create(*args, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(module, "_WORKER", "import time; time.sleep(10)")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", tracked)
    with pytest.raises(ImageError) as caught:
        await decode_qr_codes(png_bytes(), ImageLimits(decode_timeout=0.1))
    assert caught.value.code == "decode_timeout"
    assert children and children[0].returncode is not None


@pytest.mark.asyncio
async def test_decode_cancellation_reaps_child(monkeypatch):
    import maimai_updata.core.qr as module
    created = asyncio.Event()
    children = []
    real_create = asyncio.create_subprocess_exec

    async def tracked(*args, **kwargs):
        process = await real_create(*args, **kwargs)
        children.append(process)
        created.set()
        return process

    monkeypatch.setattr(module, "_WORKER", "import time; time.sleep(10)")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", tracked)
    task = asyncio.create_task(decode_qr_codes(png_bytes()))
    await created.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert children[0].returncode is not None


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/a.png", "data:image/png;base64,x",
    "http://127.0.0.1/a", "http://10.0.0.1/a", "https://192.168.1.1/a",
    "http://169.254.169.254/a", "http://[::1]/a", "http://[fc00::1]/a",
    "http://[::ffff:127.0.0.1]/a", "http://[2002:7f00:0001::]/a",
    "https://user:secret@example.com/a", "http://localhost/a", "http://foo.localhost/a",
    "https://example.com:8443/a", "https://example.com/ bad", "https://example.com\\@127.0.0.1/a",
    "http://224.0.0.1/a", "http://[fe80::1%25eth0]/a", "https://example.com/\r\nfoo",
    "http://127.000.000.001/a", "http://2130706433/a", "http://127.1/a",
    "http://[64:ff9b::7f00:1]/a",
])
def test_unsafe_urls_rejected_without_sensitive_echo(url):
    with pytest.raises(ImageError) as caught:
        validate_image_url(url)
    assert caught.value.code == "unsafe_url"
    assert url not in str(caught.value)


@pytest.mark.asyncio
async def test_resolver_rejects_mixed_public_private_answers(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
    ]))
    with pytest.raises(ImageError) as caught:
        await PublicResolver().resolve("example.com", 443)
    assert caught.value.code == "unsafe_url"


@pytest.mark.asyncio
async def test_resolver_returns_checked_addresses_for_actual_connection(monkeypatch):
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", AsyncMock(return_value=[
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443)),
    ]))
    result = await PublicResolver().resolve("example.com", 443)
    assert result[0]["host"] == "1.1.1.1"
    assert result[0]["flags"] == socket.AI_NUMERICHOST


@pytest.mark.asyncio
async def test_actual_connector_rechecks_dns_each_connection(monkeypatch):
    loop = asyncio.get_running_loop()
    lookup = AsyncMock(side_effect=[
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 443))],
        [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    ])
    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    connector = aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False)
    try:
        first = await connector._resolve_host("example.com", 443)
        assert first[0]["host"] == "1.1.1.1"
        with pytest.raises(ImageError):
            await connector._resolve_host("example.com", 443)
        assert lookup.await_count == 2
    finally:
        await connector.close()


@pytest.mark.asyncio
async def test_base64_segment_and_size_limit():
    raw = png_bytes()
    assert await ImageFetcher().fetch({"file": "base64://" + base64.b64encode(raw).decode()}) == raw
    with pytest.raises(ImageError) as caught:
        await ImageFetcher(ImageLimits(max_bytes=2)).fetch({"file": "base64://QUJD"})
    assert caught.value.code == "too_large"
    with pytest.raises(ImageError):
        await ImageFetcher().fetch({"file": "base64://%%%%"})


@pytest.mark.asyncio
async def test_onebot_file_id_resolved_with_get_image():
    raw = png_bytes()
    bot = type("Bot", (), {"get_image": AsyncMock(return_value={"file": "base64://" + base64.b64encode(raw).decode()})})()
    assert await ImageFetcher().fetch({"file": "opaque-image-id.image"}, bot) == raw
    bot.get_image.assert_awaited_once_with(file="opaque-image-id.image")


@pytest.mark.asyncio
async def test_direct_local_paths_never_read_even_with_trusted_root(tmp_path):
    local = tmp_path / "test.png"
    local.write_bytes(png_bytes())
    with pytest.raises(ImageError) as caught:
        await ImageFetcher(allowed_local_roots=[str(tmp_path)]).fetch({"file": str(local)})
    assert caught.value.code == "local_path"


@pytest.mark.asyncio
async def test_get_image_local_path_requires_root_and_rejects_symlinks(tmp_path):
    root = tmp_path / "allowed"
    root.mkdir()
    raw = png_bytes()
    local = root / "test.png"
    local.write_bytes(raw)
    bot = type("Bot", (), {"get_image": AsyncMock(return_value={"file": str(local)})})()
    with pytest.raises(ImageError):
        await ImageFetcher().fetch({"file": "test.image"}, bot)
    assert await ImageFetcher(allowed_local_roots=[str(root)]).fetch({"file": "test.image"}, bot) == raw
    outside = tmp_path / "outside.png"
    outside.write_bytes(raw)
    symlink = root / "escape.png"
    symlink.symlink_to(outside)
    bot.get_image.return_value = {"file": str(symlink)}
    with pytest.raises(ImageError):
        await ImageFetcher(allowed_local_roots=[str(root)]).fetch({"file": "test.image"}, bot)
    bot.get_image.return_value = {"file": str(root / ".." / "outside.png")}
    with pytest.raises(ImageError):
        await ImageFetcher(allowed_local_roots=[str(root)]).fetch({"file": "test.image"}, bot)


class FakeContent:
    def __init__(self, chunks):
        self.chunks = chunks

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


class FakeResponse:
    def __init__(self, status=200, headers=None, chunks=None, delay=0):
        self.status = status
        self.headers = headers or {"Content-Type": "image/png"}
        self.content = FakeContent(chunks or [b"image"])
        self.delay = delay

    async def __aenter__(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self

    async def __aexit__(self, *args):
        return None


def mock_http(monkeypatch, responses):
    import maimai_updata.core.image_fetch as module
    calls = []
    settings = []

    class Session:
        def __init__(self, **kwargs):
            settings.append(kwargs)
            self.connector = kwargs["connector"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            await self.connector.close()

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return responses.pop(0)

    monkeypatch.setattr(module.aiohttp, "ClientSession", Session)
    return calls, settings


@pytest.mark.asyncio
async def test_redirect_to_internal_host_rejected_before_request(monkeypatch):
    calls, settings = mock_http(monkeypatch, [FakeResponse(302, {"Location": "http://127.0.0.1/private"})])
    with pytest.raises(ImageError) as caught:
        await ImageFetcher().fetch({"url": "https://example.com/image"})
    assert caught.value.code == "unsafe_url"
    assert len(calls) == 1
    assert calls[0][1] == {"allow_redirects": False, "proxy": None}
    assert settings[0]["trust_env"] is False
    assert settings[0]["auto_decompress"] is False


@pytest.mark.asyncio
async def test_redirect_limit(monkeypatch):
    calls, _ = mock_http(monkeypatch, [FakeResponse(302, {"Location": "/next"}) for _ in range(4)])
    with pytest.raises(ImageError) as caught:
        await ImageFetcher().fetch({"url": "https://example.com/image"})
    assert caught.value.code == "redirect"
    assert len(calls) == 4


@pytest.mark.asyncio
async def test_safe_relative_redirect_and_transport_options(monkeypatch):
    raw = png_bytes()
    calls, settings = mock_http(monkeypatch, [
        FakeResponse(302, {"Location": "/actual.png"}),
        FakeResponse(chunks=[raw]),
    ])
    assert await ImageFetcher().fetch({"url": "https://example.com/image"}) == raw
    assert calls[1][0] == "https://example.com/actual.png"
    assert isinstance(settings[0]["connector"]._resolver, PublicResolver)
    assert settings[0]["connector"].use_dns_cache is False


@pytest.mark.asyncio
@pytest.mark.parametrize("response,code", [
    (FakeResponse(headers={"Content-Length": "99999"}), "too_large"),
    (FakeResponse(chunks=[b"a" * 80, b"b" * 80]), "too_large"),
    (FakeResponse(headers={"Content-Type": "text/html"}), "format"),
    (FakeResponse(headers={"Content-Encoding": "gzip"}), "encoding"),
    (FakeResponse(status=503), "http_status"),
])
async def test_stream_limits_and_response_validation(monkeypatch, response, code):
    mock_http(monkeypatch, [response])
    with pytest.raises(ImageError) as caught:
        await ImageFetcher(ImageLimits(max_bytes=100)).fetch({"url": "https://example.com/image"})
    assert caught.value.code == code


@pytest.mark.asyncio
async def test_http_timeout(monkeypatch):
    mock_http(monkeypatch, [FakeResponse(delay=1)])
    with pytest.raises(ImageError) as caught:
        await ImageFetcher(ImageLimits(timeout=0.01)).fetch({"url": "https://example.com/image"})
    assert caught.value.code == "timeout"


@pytest.mark.asyncio
async def test_get_image_timeout():
    async def stuck(**kwargs):
        await asyncio.sleep(1)
    bot = type("Bot", (), {})()
    bot.get_image = stuck
    with pytest.raises(ImageError) as caught:
        await ImageFetcher(ImageLimits(timeout=0.01)).fetch({"file": "id.image"}, bot)
    assert caught.value.code == "timeout"
