"""Real maimai-py 1.5.2 providers; only FFI and outbound HTTP are mocked."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from maimai_ffi import arcade
from maimai_py import MaimaiClientMultithreading
from maimai_py.enums import LevelIndex
from maimai_py.exceptions import AimeServerError, TitleServerBlockedError

from maimai_updata.core.uploader import MaimaiUploader, UploadError


CODE = "SGWCMAIDTEST-NOT-A-REAL-ACCOUNT"
TOKEN = "TEST-NOT-A-REAL-PERSONAL-TOKEN"


class Songs:
    def __init__(self, disabled=False):
        self.disabled = disabled

    async def by_id(self, song_id):
        if song_id != 1:
            return None
        return SimpleNamespace(
            title="Synthetic Test Song", disabled=self.disabled,
            get_difficulty=lambda *_: SimpleNamespace(level="12", level_index=LevelIndex.MASTER, level_value=12.0),
        )


def old_record(target):
    common = dict(level="12", level_index=3, achievements=100.1, fc="ap", fs="fsd", rate="sss")
    if target == "divingfish":
        return dict(common, song_id=1, dxScore=1100, ra=250)
    return dict(common, id=1, dx_score=1100, dx_rating=250, type="standard")


@pytest.fixture
def rig(monkeypatch):
    """Creates an actual client, exercises FFI wrapper + serializers + headers."""
    clients = []
    calls = []
    state = dict(target="divingfish", response=None, status=200, post_error=None,
                 read_status=200, read_data=None, raw_scores=None, disabled=False, delay=0)

    async def get_uid(code, http_proxy=None):
        assert code == CODE
        return b"SYNTHETIC_ENCRYPTED_IDENTIFIER"

    async def get_scores(identifier, http_proxy=None):
        assert identifier == b"SYNTHETIC_ENCRYPTED_IDENTIFIER"
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        return state["raw_scores"] if state["raw_scores"] is not None else [
            {"musicId": 1, "level": 3, "achievement": 1000000, "dx_score": 1000},
        ]

    monkeypatch.setattr(arcade, "get_uid_encrypted", get_uid)
    monkeypatch.setattr(arcade, "get_user_scores", get_scores)

    async def handler(request):
        calls.append(request)
        if request.method == "GET":
            data = state["read_data"]
            if data is None:
                records = [old_record(state["target"])]
                data = {"records": records} if state["target"] == "divingfish" else {"success": True, "code": 200, "data": records}
            return httpx.Response(state["read_status"], json=data)
        if state["post_error"]:
            raise state["post_error"]("SENSITIVE UPSTREAM ERROR " + TOKEN, request=request)
        body = state["response"]
        if body is None:
            body = {"message": "更新成功", "updates": 1, "creates": 0} if state["target"] == "divingfish" else {"success": True, "code": 200, "data": None}
        return httpx.Response(state["status"], json=body)

    def factory(_):
        client = MaimaiClientMultithreading(transport=httpx.MockTransport(handler), trust_env=False)
        async def songs(*args, **kwargs):
            return Songs(state["disabled"])
        client.songs = songs
        clients.append(client)
        return client

    monkeypatch.setattr(MaimaiUploader, "_make_client", factory)
    return state, calls, clients


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["divingfish", "lxns"])
async def test_real_provider_payload_credentials_success_and_close(rig, target):
    state, calls, clients = rig
    state["target"] = target
    result = await MaimaiUploader().upload(CODE, target, TOKEN)
    assert result.submitted_count == 1
    assert result.accepted_count == (1 if target == "divingfish" else None)
    assert all(client._client.is_closed for client in clients)
    posts = [r for r in calls if r.method == "POST"]
    assert len(posts) == 1
    request = posts[0]
    assert request.headers["Import-Token" if target == "divingfish" else "X-User-Token"] == TOKEN
    assert "developer-token" not in request.headers
    body = json.loads(request.content)
    score = body[0] if target == "divingfish" else body["scores"][0]
    # Arcade has no FC/FS. Same-account reads must preserve existing statuses.
    assert score["fc"] == "ap" and score["fs"] == "fsd"
    assert score["achievements"] == 100.1
    assert score["dxScore" if target == "divingfish" else "dx_score"] == 1100
    assert CODE not in result.message and TOKEN not in result.message
    assert request.url.path == ("/api/maimaidxprober/player/update_records" if target == "divingfish" else "/api/v0/user/maimai/player/scores")


@pytest.mark.asyncio
async def test_lxns_personal_jwt_uses_bearer_not_developer_auth(rig):
    state, calls, _ = rig
    state["target"] = "lxns"
    await MaimaiUploader().upload(CODE, "lxns", "synthetic.personal.jwt")
    assert all(r.headers["Authorization"] == "Bearer synthetic.personal.jwt" for r in calls)
    assert all("X-User-Token" not in r.headers for r in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("target,body", [
    ("lxns", {"success": False, "code": 200, "message": TOKEN}),
    ("lxns", {"success": False, "code": 500, "message": TOKEN}),
    ("divingfish", {"message": "failed " + TOKEN}),
    ("divingfish", {"message": "更新成功", "success": False, "updates": 1, "creates": 0}),
    ("divingfish", {"message": "更新成功"}),
])
async def test_http_200_does_not_imply_success(rig, target, body):
    state, calls, clients = rig
    state.update(target=target, response=body)
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, target, TOKEN)
    assert caught.value.uncertain
    assert TOKEN not in str(caught.value)
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert clients[0]._client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["divingfish", "lxns"])
@pytest.mark.parametrize("exc", [httpx.ReadTimeout, httpx.ConnectError])
async def test_non_idempotent_upload_is_never_retried(rig, target, exc):
    state, calls, clients = rig
    state.update(target=target, post_error=exc)
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, target, TOKEN)
    assert caught.value.uncertain
    assert TOKEN not in str(caught.value)
    assert len([r for r in calls if r.method == "POST"]) == 1
    assert clients[0]._client.is_closed


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "credentials"), (403, "credentials"), (429, "rate_limited"), (503, "unavailable")])
async def test_target_error_status_mapping(rig, status, code):
    state, _, _ = rig
    state.update(status=status, response={"message": TOKEN})
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == code
    assert TOKEN not in str(caught.value)


@pytest.mark.asyncio
async def test_partial_update_does_not_claim_complete_success(rig):
    state, _, _ = rig
    state["response"] = {"message": "更新成功", "updates": 0, "creates": 0}
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == "partial"
    assert caught.value.uncertain


@pytest.mark.asyncio
async def test_no_scores_stops_before_target_write(rig):
    state, calls, clients = rig
    state["raw_scores"] = []
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == "no_scores"
    assert not calls
    assert clients[0]._client.is_closed


@pytest.mark.asyncio
async def test_disabled_lxns_song_is_not_posted(rig):
    state, calls, _ = rig
    state.update(target="lxns", disabled=True)
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "lxns", TOKEN)
    assert caught.value.code == "no_scores"
    assert not [r for r in calls if r.method == "POST"]


@pytest.mark.asyncio
async def test_cannot_read_existing_scores_stops_before_destructive_upload(rig):
    state, calls, _ = rig
    state.update(read_status=401, read_data={"message": "导入token有误"})
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == "credentials"
    assert not [r for r in calls if r.method == "POST"]


@pytest.mark.asyncio
@pytest.mark.parametrize("error,expected", [(AimeServerError, "expired_code"), (TitleServerBlockedError, "arcade_blocked")])
async def test_ffi_errors_are_safe(rig, monkeypatch, error, expected):
    async def broken(*args, **kwargs):
        raise error(TOKEN)
    monkeypatch.setattr(arcade, "get_uid_encrypted", broken)
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == expected
    assert TOKEN not in str(caught.value)


@pytest.mark.asyncio
async def test_total_timeout_cancels_read_and_closes(rig):
    state, calls, clients = rig
    state["delay"] = 0.2
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader(timeout=0.01).upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == "timeout" and not caught.value.uncertain
    assert clients[0]._client.is_closed
    assert not [r for r in calls if r.method == "POST"]


@pytest.mark.asyncio
async def test_missing_credentials_and_multiple_codes_never_create_client(rig):
    _, _, clients = rig
    for code, token, error in [(CODE, "", "missing_credentials"), (CODE + " SGWCMAIDanother", TOKEN, "invalid_code")]:
        with pytest.raises(UploadError) as caught:
            await MaimaiUploader().upload(code, "divingfish", token)
        assert caught.value.code == error
    assert not clients


@pytest.mark.asyncio
async def test_failed_request_can_be_retried_with_fresh_session(rig):
    state, _, clients = rig
    state["post_error"] = httpx.ReadTimeout
    uploader = MaimaiUploader()
    with pytest.raises(UploadError):
        await uploader.upload(CODE, "divingfish", TOKEN)
    state["post_error"] = None
    result = await uploader.upload(CODE, "divingfish", TOKEN)
    assert result.accepted_count == 1
    assert len(clients) == 2 and clients[0] is not clients[1]
    assert all(client._client.is_closed for client in clients)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(429, "rate_limited"), (503, "unavailable")])
async def test_upstream_http_errors_have_safe_specific_messages(rig, monkeypatch, status, expected):
    async def broken(*args, **kwargs):
        request = httpx.Request("GET", "https://example.invalid/synthetic")
        response = httpx.Response(status, request=request)
        raise httpx.HTTPStatusError(TOKEN, request=request, response=response)
    monkeypatch.setattr(arcade, "get_uid_encrypted", broken)
    with pytest.raises(UploadError) as caught:
        await MaimaiUploader().upload(CODE, "divingfish", TOKEN)
    assert caught.value.code == expected
    assert not caught.value.uncertain
    assert TOKEN not in str(caught.value)


@pytest.mark.asyncio
async def test_cancellation_closes_client_and_never_posts(rig):
    state, calls, clients = rig
    state["delay"] = 10
    task = asyncio.create_task(MaimaiUploader().upload(CODE, "divingfish", TOKEN))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert clients[0]._client.is_closed
    assert not [r for r in calls if r.method == "POST"]
