"""One common pipeline for commands, bare codes and image messages."""
import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from collections import OrderedDict

from .database import Database, StorageError
from .core.parser import parse_codes, InvalidCode
from .core.image_fetch import ImageFetcher, ImageLimits, ImageError
from .core.qr import decode_qr_codes
from .core.uploader import MaimaiUploader, UploadError

log = logging.getLogger('maimai_updata')
NAMES = {'divingfish': '水鱼', 'lxns': '落雪'}
BINDS = {'水鱼导入token': 'divingfish', '落雪个人密钥': 'lxns'}
PRIVATE_WARNING = '上传凭据只能私聊绑定；请添加机器人好友后私聊。群里已经发出的凭据可能已泄露，请到查分器撤销或更换。'


class TTLCache:
    def __init__(self, maximum=4096, clock=time.monotonic):
        self.data = OrderedDict()
        self.maximum = maximum
        self.clock = clock

    def has(self, key):
        expiry = self.data.get(key, 0)
        if expiry <= self.clock():
            self.data.pop(key, None)
            return False
        return True

    def put(self, key, ttl):
        self.data.pop(key, None)
        self.data[key] = self.clock() + ttl
        while len(self.data) > self.maximum:
            self.data.popitem(last=False)

    def clear_user(self, uid):
        for key in list(self.data):
            if isinstance(key, tuple) and key[0] == uid:
                self.data.pop(key, None)


def _message_parts(event):
    message = event.get('message', [])
    if isinstance(message, str):
        # Real aiocqhttp supplies Message; parsing strings as CQ prevents paths
        # and markup from being silently treated as file-system references.
        from aiocqhttp.message import Message
        message = Message(message)
    texts, images = [], []
    for segment in message:
        kind = segment.get('type') if isinstance(segment, dict) else segment.type
        data = segment.get('data', {}) if isinstance(segment, dict) else segment.data
        if kind == 'text':
            texts.append(data.get('text', ''))
        elif kind == 'image':
            images.append(data)
    return ''.join(texts).strip(), images


class Application:
    def __init__(self, config, *, database=None, uploader=None, fetcher=None, decoder=None):
        self.config = config
        self._database = database
        self.uploader = uploader or MaimaiUploader(timeout=config.upload_timeout, arcade_proxy=config.arcade_proxy)
        self.limits = ImageLimits(max_bytes=config.max_image_bytes, timeout=config.image_timeout, max_pixels=config.max_pixels)
        self.fetcher = fetcher or ImageFetcher(self.limits, allowed_local_roots=config.local_image_roots)
        self.decoder = decoder or decode_qr_codes
        self.busy = set()
        self.active_codes = set()
        self.slots = asyncio.Semaphore(config.max_concurrent)
        self.messages = TTLCache()
        self.codes = TTLCache()
        self.cooldowns = TTLCache()
        self._hash_key = secrets.token_bytes(32)

    async def _db(self, method, *args):
        def run():
            if self._database is None:
                self._database = Database(self.config.data_dir, self.config.encryption_key)
            return getattr(self._database, method)(*args)
        return await asyncio.to_thread(run)

    def help(self):
        return ('舞萌成绩上传：\n'
                '先私聊绑定：水鱼导入token <导入Token> 或 落雪个人密钥 <个人API密钥>\n'
                '选择：上传源 水鱼 / 上传源 落雪\n'
                f'上传：{self.config.upload_command} SGWCMAID…，或直接发送有效二维码图片；也支持命令后附图。\n'
                '查看：上传配置；删除：删除上传凭据 / 删除水鱼token / 删除落雪密钥\n'
                '二维码也属于敏感信息，建议私聊发送。只处理您本人授权的账户。')

    def _fingerprint(self, value):
        return hmac.new(self._hash_key, value.encode(), hashlib.sha256).digest()

    async def handle(self, bot, event, auto_allowed=True):
        text, images = _message_parts(event)
        private = event.get('message_type') == 'private'
        uid = str(event.get('user_id', ''))
        if not uid.isdecimal() or event.get('anonymous'):
            return None
        lower = text.lower()
        binding = next((name for name in BINDS if lower.startswith(name)), None)
        # Never inspect/store the supplied secret in a group.
        if binding and not private:
            return PRIVATE_WARNING
        if text == '舞萌上传帮助':
            return self.help()
        command = self.config.upload_command
        explicit = text.startswith(command)
        bare = self.config.allow_bare_codes and text.startswith('SGWCMAID')
        passive = bool(images and not explicit and not bare and self.config.auto_images and auto_allowed)
        management = binding or text.startswith('上传源') or text in ('上传配置', '删除上传凭据', '删除水鱼token', '删除水鱼Token', '删除落雪密钥')
        if not (management or explicit or bare or passive):
            return None
        if uid in self.busy:
            return None if passive else '您有一个上传或配置请求正在处理，请等待完成。'
        self.busy.add(uid)
        try:
            if management:
                return await self._manage(uid, text, binding)
            msgid = event.get('message_id')
            message_key = (uid, event.get('self_id'), event.get('message_type'), event.get('group_id'), msgid)
            if msgid is not None and self.messages.has(message_key):
                return None if passive else '这是重复消息，已忽略；如需重试，请重新发送。'
            if self.cooldowns.has(uid):
                return None if passive else '请求过于频繁，请稍后再试。'
            if self.slots.locked():
                return None if passive else '上传/识别任务已满，请稍后再试。'
            self.cooldowns.put(uid, self.config.cooldown)
            if msgid is not None:
                self.messages.put(message_key, self.config.duplicate_ttl)
            async with self.slots:
                return await self._process(bot, uid, text[len(command):].strip() if explicit else (text if bare else ''), images, passive)
        except StorageError as error:
            return str(error)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            # Never log str(error), event, traceback or upstream response bodies.
            log.warning('upload application failure type=%s', type(error).__name__)
            return None if passive else '处理失败，请稍后重试或联系管理员检查依赖及配置。'
        finally:
            self.busy.discard(uid)

    async def _manage(self, uid, text, binding):
        if binding:
            token = text[len(binding):].strip()
            if not token:
                return '请在命令后附上对应查分器的个人凭据。'
            target = BINDS[binding]
            await self._db('bind', uid, target, token)
            return f'已加密保存您的{NAMES[target]}凭据。请用「上传源 {NAMES[target]}」选择上传目标。'
        if text.startswith('上传源'):
            name = text[len('上传源'):].strip()
            target = next((key for key,value in NAMES.items() if value == name), None)
            if target is None:
                return '请选择「上传源 水鱼」或「上传源 落雪」。'
            await self._db('set_target', uid, target)
            if not await self._db('get_secret', uid, target):
                return f'已选择{NAMES[target]}，但尚未绑定该源凭据。' + self._missing(target)
            return f'已选择{NAMES[target]}作为上传目标。'
        if text == '上传配置':
            target = await self._db('get_target', uid)
            bound = await self._db('status', uid)
            return f'当前上传源：{NAMES[target]}；水鱼：' + ('已绑定' if 'divingfish' in bound else '未绑定') + '；落雪：' + ('已绑定' if 'lxns' in bound else '未绑定')
        target = None if text == '删除上传凭据' else ('divingfish' if text.lower() == '删除水鱼token' else 'lxns')
        await self._db('delete', uid, target)
        self.codes.clear_user(uid)
        self.messages.clear_user(uid)
        self.cooldowns.data.pop(uid, None)
        return '已删除您的' + (NAMES[target] if target else '全部上传') + '凭据。'

    @staticmethod
    def _missing(target):
        return '请私聊发送「水鱼导入token <导入Token>」。' if target == 'divingfish' else '请私聊发送「落雪个人密钥 <个人API密钥>」。'

    async def _process(self, bot, uid, text, images, passive):
        if len(images) > self.config.max_images:
            return None if passive else f'一次最多处理 {self.config.max_images} 张图片，请只发送一个账户的二维码。'
        try:
            codes = set(parse_codes(text)) if text else set()
        except InvalidCode:
            return '二维码文本无效，请发送完整 SGWCMAID 内容或二维码图片。'
        for segment in images:
            try:
                data = await self.fetcher.fetch(segment, bot=bot)
                decoded = await self.decoder(data, self.limits)
                for value in decoded:
                    try:
                        codes.update(parse_codes(value))
                    except InvalidCode:
                        continue
            except ImageError as error:
                # In a multi-image message, never choose from an incomplete scan.
                return None if passive else str(error)
        if not codes:
            return None if passive else '未识别到有效舞萌二维码，请发送清晰的原图或完整 SGWCMAID 文本。'
        if len(codes) > 1:
            return '发现多个不同舞萌二维码，请一次只提交一个账户的二维码。'
        code = codes.pop()
        target = await self._db('get_target', uid)
        credential = await self._db('get_secret', uid, target)
        if not credential:
            return f'尚未绑定当前目标{NAMES[target]}的凭据。' + self._missing(target)
        digest = self._fingerprint(code)
        key = (uid, target, digest)
        if self.codes.has(key) or digest in self.active_codes:
            return '该二维码正在处理或近期已提交，请先检查查分器，稍后再试。'
        self.active_codes.add(digest)
        try:
            result = await self.uploader.upload(code, target, credential)
            self.codes.put(key, self.config.duplicate_ttl)
            return result.message
        except UploadError as error:
            if error.uncertain:
                self.codes.put(key, self.config.duplicate_ttl)
            return error.message
        finally:
            self.active_codes.discard(digest)
            credential = None
            code = None
