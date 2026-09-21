"""Decode QR payloads in killable, resource-limited child processes."""
import asyncio
import json
import sys
import weakref
from typing import List, Optional

from .image_fetch import ImageError, ImageLimits

# Child receives only bounded bytes over stdin and returns bounded JSON. No
# image or QR payload is written to a filesystem or sent to a logger.
_WORKER = r'''
import io, json, sys, warnings
max_bytes, max_pixels = int(sys.argv[1]), int(sys.argv[2])
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (4, 4))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except (ImportError, ValueError, OSError):
    pass
try:
    from PIL import Image, ImageOps
    import zxingcpp
    Image.MAX_IMAGE_PIXELS = max_pixels
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    raw = sys.stdin.buffer.read(max_bytes + 1)
    if not raw or len(raw) > max_bytes:
        print(json.dumps({"error":"too_large"})); sys.exit(0)
    with Image.open(io.BytesIO(raw)) as source:
        if source.format not in ("PNG", "JPEG", "GIF", "WEBP", "BMP"):
            print(json.dumps({"error":"format"})); sys.exit(0)
        if source.width <= 0 or source.height <= 0 or source.width * source.height > max_pixels:
            print(json.dumps({"error":"pixels"})); sys.exit(0)
        if getattr(source, "n_frames", 1) > 1:
            print(json.dumps({"error":"animated"})); sys.exit(0)
        source.load()
        frame = ImageOps.exif_transpose(source).convert("L")
        # Pillow 9.1's direct object path requires optional numpy. A shaped
        # grayscale buffer uses zxing-cpp's native API without that dependency.
        pixels = memoryview(frame.tobytes()).cast("B", shape=(frame.height, frame.width))
        found = zxingcpp.read_barcodes(pixels, formats=zxingcpp.BarcodeFormat.QRCode)
        values = list(dict.fromkeys(item.text for item in found if item.valid))
        if len(values) > 32 or any(len(value) > 8192 for value in values):
            print(json.dumps({"error":"complexity"})); sys.exit(0)
        print(json.dumps({"values":values}, ensure_ascii=True))
except (Image.DecompressionBombError, Image.DecompressionBombWarning):
    print(json.dumps({"error":"pixels"}))
except Exception:
    print(json.dumps({"error":"decode"}))
'''

_DECODE_SLOTS = weakref.WeakKeyDictionary()


def _slots(count: int):
    loop = asyncio.get_running_loop()
    key = _DECODE_SLOTS.get(loop)
    if key is None:
        key = asyncio.Semaphore(count)
        _DECODE_SLOTS[loop] = key
    return key


async def _stop_process(process):
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            return
    await process.wait()


async def decode_qr_codes(data: bytes, limits: Optional[ImageLimits] = None) -> List[str]:
    """Return all distinct QR strings, or [] for a valid ordinary image.

    Unsupported/corrupt/oversized images raise a safe ImageError. SGWCMAID
    syntax and multi-account decisions belong to the shared text parser.
    """
    limits = limits or ImageLimits()
    if not isinstance(data, bytes) or not data:
        raise ImageError("empty", "图片内容为空或已损坏，请重新发送原图。")
    if len(data) > limits.max_bytes:
        raise ImageError("too_large", "图片超过允许的大小，请缩小后重试。")
    process = None
    acquired = False
    semaphore = _slots(limits.max_concurrent_decodes)
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=limits.decode_timeout)
        acquired = True
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-I", "-c", _WORKER, str(limits.max_bytes), str(limits.max_pixels),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=512 * 1024,
        )
        output, _ = await asyncio.wait_for(process.communicate(data), timeout=limits.decode_timeout)
        if process.returncode != 0 or len(output) > 512 * 1024:
            raise ImageError("decode", "二维码图片识别失败，请重新发送清晰原图。")
        try:
            result = json.loads(output)
        except (ValueError, UnicodeError):
            raise ImageError("decode", "二维码图片识别失败，请重新发送清晰原图。") from None
        messages = {
            "pixels": "图片像素过大，请缩小后重新发送。",
            "too_large": "图片超过允许的大小，请缩小后重试。",
            "format": "图片类型不受支持，请使用 PNG、JPEG 或静态 WebP。",
            "animated": "请发送静态二维码原图，不支持动画图片。",
            "complexity": "图片包含过多二维码或内容过长，请一次发送一个二维码。",
            "decode": "图片已损坏或无法识别，请重新发送原图。",
        }
        if "error" in result:
            code = result["error"]
            raise ImageError(code, messages.get(code, messages["decode"]))
        values = result.get("values")
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ImageError("decode", messages["decode"])
        return values
    except asyncio.TimeoutError:
        raise ImageError("decode_timeout", "二维码识别超时或当前繁忙，请稍后重试。") from None
    except (OSError, RuntimeError):
        raise ImageError("decode", "二维码识别服务暂时不可用，请联系管理员。") from None
    finally:
        if process is not None:
            await _stop_process(process)
        if acquired:
            semaphore.release()
