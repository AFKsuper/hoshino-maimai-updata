"""Bounded image transport for OneBot v11 image segments.

Only ``get_image`` responses may select explicitly trusted local resources.
HTTP connections resolve through a validating resolver on every connection.
"""
import asyncio
import base64
import binascii
import ipaddress
import os
import socket
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.parse import urljoin, urlsplit

import aiohttp


class ImageError(Exception):
    """An image failure with a public message that contains no input data."""

    def __init__(self, code: str, safe_message: str):
        self.code = code
        self.safe_message = safe_message
        super().__init__(safe_message)


@dataclass(frozen=True)
class ImageLimits:
    max_bytes: int = 8 * 1024 * 1024
    timeout: float = 10.0
    max_pixels: int = 12_000_000
    decode_timeout: float = 5.0
    max_redirects: int = 3
    max_concurrent_fetches: int = 4
    max_concurrent_decodes: int = 2

    def __post_init__(self):
        if any(value <= 0 for value in (
            self.max_bytes, self.timeout, self.max_pixels, self.decode_timeout,
            self.max_concurrent_fetches, self.max_concurrent_decodes,
        )) or self.max_redirects < 0:
            raise ValueError("图片资源限制必须为正数，重定向上限不得为负数")


def _public_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    # Reject IPv6 transition formats rather than depend on routing-specific
    # interpretation of their embedded IPv4 address.
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.sixtofour or address.teredo:
            return False
        if address in ipaddress.ip_network("64:ff9b::/96") or address in ipaddress.ip_network("64:ff9b:1::/48"):
            return False
    return address.is_global and not address.is_multicast


def validate_image_url(url: str) -> str:
    """Validate syntax and literal IPs; DNS validation happens in the connector."""
    try:
        if not isinstance(url, str) or len(url) > 8192:
            raise ValueError
        if any(ord(char) < 33 or ord(char) == 127 for char in url) or "\\" in url:
            raise ValueError
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ("https", "http") or not parsed.hostname:
            raise ValueError
        if parsed.username is not None or parsed.password is not None:
            raise ValueError
        if parsed.port is not None and parsed.port not in (80, 443):
            raise ValueError
        host = parsed.hostname.rstrip(".")
        if not host or "%" in host or host.lower() == "localhost" or host.lower().endswith(".localhost"):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            # aiohttp 3.8 recognizes dotted literals with leading zeroes as
            # IPs and skips its resolver; libc may interpret these as octal.
            # Reject noncanonical numeric literals before that fast path.
            if all(char in "0123456789." for char in host):
                raise ValueError
            # Numeric and unusual IPv4 spellings are still checked after libc
            # getaddrinfo resolves them (e.g. 0x7f000001).
            host.encode("idna")
        else:
            if not _public_address(host):
                raise ValueError
    except (ValueError, UnicodeError, TypeError):
        raise ImageError("unsafe_url", "图片地址不符合安全要求，请重新发送二维码图片。") from None
    return url


class PublicResolver(aiohttp.abc.AbstractResolver):
    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, family=family)
        if not infos or any(not _public_address(info[4][0]) for info in infos):
            raise ImageError("unsafe_url", "图片地址解析到不允许访问的网络，请重新发送图片。")
        resolved = []
        seen = set()
        for address_family, _, proto, _, sockaddr in infos:
            address = sockaddr[0]
            key = (address_family, address)
            if key in seen:
                continue
            seen.add(key)
            resolved.append({
                "hostname": host, "host": address, "port": port,
                "family": address_family, "proto": proto,
                "flags": socket.AI_NUMERICHOST,
            })
        return resolved

    async def close(self):
        return None


class ImageFetcher:
    def __init__(self, limits: Optional[ImageLimits] = None,
                 allowed_local_roots: Sequence[str] = ()):
        self.limits = limits or ImageLimits()
        self.allowed_local_roots = tuple(Path(root).resolve() for root in allowed_local_roots)
        if any(root == Path(root.anchor) for root in self.allowed_local_roots):
            raise ValueError("受信任图片目录不得是文件系统根目录")
        self._slots = asyncio.Semaphore(self.limits.max_concurrent_fetches)

    async def fetch(self, segment_data: Mapping[str, Any], bot: Any = None) -> bytes:
        """Read one CQ image segment's ``data`` with a bounded total duration."""
        try:
            async def guarded():
                async with self._slots:
                    return await self._fetch(segment_data, bot)
            return await asyncio.wait_for(guarded(), timeout=self.limits.timeout)
        except asyncio.TimeoutError:
            raise ImageError("timeout", "读取二维码图片超时，请稍后重试。") from None
        except ImageError:
            raise
        except (aiohttp.ClientError, OSError, ValueError, TypeError):
            raise ImageError("download", "无法读取二维码图片，请重新发送原图。") from None

    async def _fetch(self, data: Mapping[str, Any], bot: Any) -> bytes:
        if not isinstance(data, Mapping):
            raise ImageError("source", "图片消息格式无法识别。")
        url = data.get("url")
        if isinstance(url, str) and url:
            return await self._fetch_url(url)
        value = data.get("file")
        if not isinstance(value, str) or not value or len(value) > (self.limits.max_bytes * 4 // 3 + 4096):
            raise ImageError("source", "图片消息缺少可读取的资源。")
        if value.startswith("base64://"):
            return self._decode_base64(value[9:])
        if value.startswith(("https://", "http://")):
            return await self._fetch_url(value)
        # Ordinary message data can never request a local path, even inside a
        # configured trusted root. get_image must resolve an opaque file ID.
        if "/" in value or "\\" in value or ":" in value or value in (".", ".."):
            raise ImageError("local_path", "不能从消息直接读取本地图片路径，请重新发送图片。")
        if len(value) > 1024:
            raise ImageError("source", "图片资源标识过长，请重新发送图片。")
        if bot is None:
            raise ImageError("source", "QQ 接入端未提供可读取的图片地址。")
        try:
            result = await bot.get_image(file=value)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ImageError("source", "QQ 接入端无法获取该图片，请重新发送原图。") from None
        if isinstance(result, Mapping) and "data" in result and isinstance(result["data"], Mapping):
            result = result["data"]
        if not isinstance(result, Mapping):
            raise ImageError("source", "QQ 接入端返回的图片信息无法识别。")
        remote = result.get("url")
        if isinstance(remote, str) and remote:
            return await self._fetch_url(remote)
        source = result.get("file")
        if not isinstance(source, str) or not source:
            source = result.get("base64")
            if isinstance(source, str) and source:
                return self._decode_base64(source.removeprefix("base64://"))
            raise ImageError("source", "QQ 接入端没有返回可读取的图片资源。")
        if source.startswith("base64://"):
            return self._decode_base64(source[9:])
        if source.startswith(("http://", "https://")):
            return await self._fetch_url(source)
        # The OneBot v11 get_image API may return a server-local absolute path.
        # This is supported only for colocated adapters with explicit roots.
        if source.startswith("file://"):
            parsed = urlsplit(source)
            if parsed.netloc not in ("", "localhost") or parsed.query or parsed.fragment:
                raise ImageError("local_path", "接入端本地图片地址不在允许范围。")
            source = parsed.path
        return await asyncio.to_thread(self._read_trusted_local, source)

    def _decode_base64(self, encoded: str) -> bytes:
        if len(encoded) > ((self.limits.max_bytes + 2) // 3) * 4:
            raise ImageError("too_large", "图片超过允许的大小，请缩小后重试。")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            raise ImageError("source", "图片数据已损坏，请重新发送原图。") from None
        self._check_size(len(raw))
        return raw

    def _check_size(self, size: int):
        if size > self.limits.max_bytes:
            raise ImageError("too_large", "图片超过允许的大小，请缩小后重试。")
        if size == 0:
            raise ImageError("empty", "图片内容为空，请重新发送原图。")

    def _read_trusted_local(self, filename: str) -> bytes:
        path = Path(filename)
        if not path.is_absolute() or not self.allowed_local_roots:
            raise ImageError("local_path", "接入端仅提供本地图片，请管理员配置受信任图片目录或启用图片 URL。")
        selected = None
        for root in self.allowed_local_roots:
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if relative.parts and all(part not in (".", "..") for part in relative.parts):
                selected = (root, relative)
                break
        if selected is None:
            raise ImageError("local_path", "接入端图片路径不在受信任目录内。")
        root, relative = selected
        # Traverse with dir_fd + O_NOFOLLOW to prevent symlink races escaping
        # the trusted root. Trusted local access intentionally requires POSIX.
        if not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
            raise ImageError("local_path", "当前系统不支持安全读取本地图片，请使用图片 URL。")
        descriptors = []
        try:
            directory = os.open(str(root), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(directory)
            for component in relative.parts[:-1]:
                directory = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                descriptors.append(directory)
            fd = os.open(relative.parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            descriptors.append(fd)
            metadata = os.fstat(fd)
            if not stat.S_ISREG(metadata.st_mode):
                raise ImageError("local_path", "接入端图片资源不是普通文件。")
            self._check_size(metadata.st_size)
            chunks = []
            size = 0
            while True:
                chunk = os.read(fd, min(65536, self.limits.max_bytes + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                self._check_size(size)
                chunks.append(chunk)
            self._check_size(size)
            return b"".join(chunks)
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)

    async def _fetch_url(self, url: str) -> bytes:
        current = validate_image_url(url)
        timeout = aiohttp.ClientTimeout(total=self.limits.timeout, connect=min(5.0, self.limits.timeout))
        connector = aiohttp.TCPConnector(
            resolver=PublicResolver(), use_dns_cache=False, family=socket.AF_UNSPEC,
            limit=self.limits.max_concurrent_fetches,
        )
        async with aiohttp.ClientSession(
            connector=connector, timeout=timeout, trust_env=False, auto_decompress=False,
            headers={"User-Agent": "Hoshino-maimai-upload/1.0", "Accept": "image/*", "Accept-Encoding": "identity"},
        ) as session:
            for redirects in range(self.limits.max_redirects + 1):
                async with session.get(current, allow_redirects=False, proxy=None) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location or redirects >= self.limits.max_redirects:
                            raise ImageError("redirect", "图片地址重定向次数过多或地址无效。")
                        current = validate_image_url(urljoin(current, location))
                        continue
                    if response.status != 200:
                        raise ImageError("http_status", "图片服务器暂时无法提供图片，请重新发送原图。")
                    if response.headers.get("Content-Encoding", "identity").lower() not in ("", "identity"):
                        raise ImageError("encoding", "图片使用了不支持的传输压缩，请重新发送原图。")
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    if content_type and content_type not in (
                        "image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/bmp",
                        "application/octet-stream", "binary/octet-stream",
                    ):
                        raise ImageError("format", "该消息资源不是受支持的图片。")
                    declared = response.headers.get("Content-Length")
                    if declared is not None:
                        try:
                            length = int(declared)
                        except ValueError:
                            raise ImageError("source", "图片服务器返回了无效资源信息。") from None
                        if length < 0:
                            raise ImageError("source", "图片服务器返回了无效资源信息。")
                        self._check_size(length)
                    chunks = []
                    size = 0
                    async for chunk in response.content.iter_chunked(65536):
                        size += len(chunk)
                        self._check_size(size)
                        chunks.append(chunk)
                    self._check_size(size)
                    return b"".join(chunks)
        raise ImageError("redirect", "无法读取图片地址。")
