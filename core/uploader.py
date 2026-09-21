"""The shared text/image uploader, audited against maimai-py == 1.5.2.

No QR, identifier or credential is logged or persisted here. Private APIs are
limited to the pinned provider serializers, HTTP client and retry unwrapping;
tests exercise these with the installed upstream package and MockTransport.
"""

import asyncio
import dataclasses
import logging
import math
from dataclasses import dataclass
from importlib.metadata import version
from typing import Optional

import httpcore
import httpx
from maimai_py import ArcadeProvider, DivingFishProvider, LXNSProvider
from maimai_py import MaimaiClientMultithreading, PlayerIdentifier
from maimai_py.exceptions import (
    AimeServerError, ArcadeIdentifierError, InvalidDeveloperTokenError,
    InvalidPlayerIdentifierError, PrivacyLimitationError,
    TitleServerBlockedError, TitleServerNetworkError,
)

from .parser import InvalidCode, parse_codes


log = logging.getLogger("maimai_updata")


class UploadError(Exception):
    """Only .message is safe for users; upstream exception text is discarded."""

    def __init__(self, code: str, message: str, uncertain: bool = False):
        self.code = code
        self.message = message
        self.uncertain = uncertain
        super().__init__(message)


@dataclass(frozen=True)
class UploadResult:
    target: str
    submitted_count: int
    skipped_count: int
    accepted_count: Optional[int]
    message: str


def _response_error(response: httpx.Response, data, posted: bool):
    """Classify error envelopes without reflecting remote messages or URLs."""
    status = response.status_code
    code = data.get("code") if isinstance(data, dict) else None
    msg = data.get("message") if isinstance(data, dict) else None
    if status in (401, 403) or code in (401, 403) or msg in (
        "导入token有误", "尚未登录", "会话过期",
    ):
        raise UploadError("credentials", "查分器凭据无效或权限不足，请通过私聊重新绑定，并检查查分器隐私设置。")
    if status == 429 or code == 429:
        raise UploadError("rate_limited", "查分器暂时限流，请稍后再试。")
    if status >= 500 or isinstance(code, int) and code >= 500:
        message = "查分器暂时不可用；上传结果未确认，请先查看查分器记录后再重试。" if posted else "查分器暂时不可用，尚未上传，请稍后再试。"
        raise UploadError("unavailable", message, posted)
    if status < 200 or status >= 300:
        raise UploadError("target_response", "查分器拒绝了请求，请检查账户初始化、个人密钥权限或稍后再试。")


class MaimaiUploader:
    def __init__(self, timeout: float = 120.0, request_timeout: float = 20.0,
                 arcade_proxy: Optional[str] = None):
        self.timeout = timeout
        self.request_timeout = request_timeout
        self.arcade_proxy = arcade_proxy

    def _make_client(self):
        # MaimaiClient itself is singleton; the non-singleton variant prevents
        # credentials, cookies and session lifetimes leaking between plugins.
        return MaimaiClientMultithreading(
            timeout=self.request_timeout, trust_env=False, follow_redirects=False,
        )

    async def upload(self, code: str, target: str, credential: str) -> UploadResult:
        try:
            codes = parse_codes(code)
        except InvalidCode:
            raise UploadError("invalid_code", "二维码文本无效，请发送完整的舞萌二维码。") from None
        if len(codes) != 1:
            raise UploadError("invalid_code", "请一次提交一个舞萌二维码。")
        if target not in ("divingfish", "lxns"):
            raise UploadError("target", "上传源配置无效，请选择水鱼或落雪。")
        if not credential:
            raise UploadError("missing_credentials", "尚未绑定当前查分器凭据，请通过私聊绑定后再上传。")
        if version("maimai-py") != "1.5.2":
            raise UploadError("dependency", "maimai-py 版本不匹配，请管理员按插件锁定依赖安装。")

        state = {"stage": "resolve", "posted": False, "confirmed": None, "submitted": 0}
        client = self._make_client()

        async def request_hook(request):
            if request.method == "POST" and request.url.path in (
                "/api/maimaidxprober/player/update_records", "/api/v0/user/maimai/player/scores",
            ):
                state["posted"] = True

        async def response_hook(response):
            # Apply stricter envelope checks than upstream 1.5.2. In that
            # release an unknown success:false/code with HTTP 200 can slip by.
            if response.request.url.host not in ("www.diving-fish.com", "maimai.lxns.net"):
                return
            if response.request.url.path not in (
                "/api/maimaidxprober/player/update_records", "/api/v0/user/maimai/player/scores",
                "/api/maimaidxprober/player/records",
            ):
                return
            await response.aread()
            try:
                data = response.json()
            except (ValueError, UnicodeError):
                _response_error(response, None, state["posted"])
                raise UploadError("target_response", "查分器返回了无法识别的响应，未能确认上传结果。", state["posted"]) from None
            _response_error(response, data, state["posted"])
            if not isinstance(data, dict):
                raise UploadError("target_response", "查分器响应格式异常，未能确认上传结果。", state["posted"])
            if target == "lxns" and (data.get("success") is not True or data.get("code", 200) != 200):
                raise UploadError("target_response", "落雪返回失败状态，未能确认上传结果。", state["posted"])
            if response.request.method != "POST":
                return
            if target == "divingfish":
                if data.get("message") != "更新成功" or data.get("success") is False:
                    raise UploadError("target_response", "水鱼未确认更新成功，请检查查分器记录。", True)
                counts = (data.get("updates"), data.get("creates"))
                if all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in counts):
                    accepted = sum(counts)
                    if accepted < state["submitted"]:
                        raise UploadError("partial", f"水鱼仅确认处理 {accepted}/{state['submitted']} 条成绩，部分条目未入库；请检查曲库同步。", True)
                    if accepted > state["submitted"]:
                        raise UploadError("target_response", "水鱼返回了异常处理数量，未能确认完整结果。", True)
                    state["confirmed"] = accepted
                else:
                    raise UploadError("target_response", "水鱼未返回有效处理数量，无法确认全部条目已入库，请先查看查分器记录。", True)
            else:
                # LXNS does not promise a per-record acknowledgement here.
                # Explicit error/partial envelopes must never be called success.
                if any(data.get(k) for k in ("errors", "failed", "failed_count")) or data.get("partial"):
                    raise UploadError("partial", "落雪返回部分失败，请先查看查分器记录后再重试。", True)
                state["confirmed"] = "request"

        client._client.event_hooks["request"].append(request_hook)
        client._client.event_hooks["response"].append(response_hook)
        try:
            return await asyncio.wait_for(self._run(codes[0], target, credential, client, state), self.timeout)
        except UploadError:
            raise
        except (AimeServerError, ArcadeIdentifierError):
            raise UploadError("expired_code", "舞萌二维码已过期、无效或被服务端拒绝，请刷新后重新发送。") from None
        except TitleServerBlockedError:
            raise UploadError("arcade_blocked", "舞萌成绩服务拒绝访问，请管理员检查服务器网络或机台接口限制。") from None
        except TitleServerNetworkError:
            raise UploadError("fetch_failed", "获取舞萌成绩失败，成绩服务暂时不可用，请稍后重试。") from None
        except (InvalidDeveloperTokenError, InvalidPlayerIdentifierError, PrivacyLimitationError):
            if state["stage"] in ("target_read", "upload"):
                raise UploadError("credentials", "查分器凭据无效、权限不足或账户未初始化，请通过私聊重新绑定并检查平台设置。") from None
            raise UploadError("invalid_code", "舞萌二维码无法解析，请刷新后重新发送。") from None
        except (asyncio.TimeoutError, httpx.TimeoutException, httpcore.TimeoutException):
            if state["posted"]:
                raise UploadError("timeout", "上传请求超时，结果尚不确定；请先查看查分器记录，稍后再重试。", True) from None
            raise UploadError("timeout", "读取数据超时，尚未发送成绩上传请求，请稍后再试。") from None
        except (httpx.RequestError, httpcore.NetworkError):
            if state["posted"]:
                raise UploadError("network", "上传连接中断，结果尚不确定；请先查看查分器记录再重试。", True) from None
            raise UploadError("network", "读取数据时网络异常，尚未上传，请稍后重试。") from None
        except httpx.HTTPStatusError as error:
            status = error.response.status_code
            if status == 429:
                raise UploadError("rate_limited", "成绩或曲库服务暂时限流，请稍后重试。", state["posted"]) from None
            if status >= 500:
                raise UploadError("unavailable", "成绩或曲库服务暂时不可用，请稍后重试。", state["posted"]) from None
            raise UploadError("upstream", "成绩或曲库服务拒绝请求，请管理员检查上游接口和网络。", state["posted"]) from None
        except Exception:
            messages = {
                "resolve": "解析舞萌二维码失败，请刷新二维码；若持续失败，请管理员检查依赖和上游接口。",
                "fetch": "获取舞萌成绩失败，请稍后重试或请管理员检查上游接口。",
                "target_read": "无法安全读取当前查分器成绩，已停止上传以保护已有记录，请检查凭据和平台状态。",
                "upload": "查分器返回异常，未能确认上传结果；请先查看查分器记录再重试。",
            }
            raise UploadError("upstream", messages[state["stage"]], state["posted"]) from None
        finally:
            # Independent per-request resources; no shared sensitive cache.
            # One failed cleanup must not mask the confirmed write result or
            # prevent attempting the other close operation.
            for close in (client._client.aclose, client._cache.close):
                try:
                    await close()
                except Exception as error:
                    log.warning("upload resource close failure type=%s", type(error).__name__)

    async def _run(self, code, target, credential, client, state):
        source = ArcadeProvider(http_proxy=self.arcade_proxy)
        identifier = await source.get_identifier(code, client)
        state["stage"] = "fetch"
        scores = await source.get_scores_all(identifier, client)
        if not scores:
            raise UploadError("no_scores", "没有获取到可上传的有效成绩。")
        provider = DivingFishProvider() if target == "divingfish" else LXNSProvider()
        target_id = PlayerIdentifier(credentials=credential)
        state["stage"] = "target_read"
        # Arcade has no FC/FS since the 1.53 update. Preserve the SAME target
        # account's existing fields instead of letting DF replace them with null.
        previous = await provider.get_scores_all(target_id, client)
        previous_by_key = {(s.id, s.type, s.level_index): s for s in previous}
        merged = {}
        for score in scores:
            if score.achievements is None or not math.isfinite(score.achievements):
                continue
            key = (score.id, score.type, score.level_index)
            score = dataclasses.replace(score)
            old = merged.get(key) or previous_by_key.get(key)
            if old is not None:
                score = score._join(old)
                score.dx_score = max(score.dx_score or 0, old.dx_score or 0)
                score.play_time = score.play_time or old.play_time
            merged[key] = score
        songs = await client.songs()
        accepted = []
        for score in merged.values():
            if await provider._ser_score(score, songs) is not None:
                accepted.append(score)
        if not accepted:
            raise UploadError("no_scores", "没有可上传的有效成绩，曲目可能未收录或已停用。")
        state["stage"] = "upload"
        state["submitted"] = len(accepted)
        # Both providers decorate update_scores with retries on RequestError.
        # Bypass only that wrapper on the EXACT pinned release: one POST only.
        await type(provider).update_scores.__wrapped__(provider, target_id, accepted, client)
        if state["confirmed"] is None:
            raise UploadError("unconfirmed", "未收到查分器的成功确认，请先查看记录后再重试。", True)
        skipped = max(0, len(scores) - len(accepted))
        count = state["confirmed"] if isinstance(state["confirmed"], int) else None
        if count is not None:
            message = f"水鱼已确认处理 {count} 条成绩。"
        else:
            message = f"落雪已确认本次上传请求成功；提交 {len(accepted)} 条成绩，平台未返回逐条入库数量。"
        if skipped:
            message += f" 本次另有 {skipped} 条读取记录未提交（无效、重复或不受目标支持）。"
        return UploadResult(target, len(accepted), skipped, count, message)


async def upload(code: str, target: str, credential: str) -> UploadResult:
    """Convenience entry; Hoshino handlers may retain a configured uploader."""
    return await MaimaiUploader().upload(code, target, credential)
