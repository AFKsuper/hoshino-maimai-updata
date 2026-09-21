"""Real NoneBot1/Hoshino dispatch smoke; QQ APIs and upload are mocked.

Run: python scripts/smoke_hoshino.py --hoshino-source /path/to/HoshinoBot
Requires the test dependencies and a compatible Hoshino runtime.
No real QQ connection, QR credential or account token is required.
The target Hoshino bytes are copied unchanged; config is a new local instance.
Hoshino's ~/.hoshino storage path is routed to this scratch instance by the
harness only, because this sandbox cannot write the real account home.
"""
import argparse
import asyncio
import base64
import io
import json
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = None
HOSHINO_SOURCE = None
PLUGIN_SOURCE = None
REPORT_PATH = None


def prepare():
    from cryptography.fernet import Fernet
    shutil.copytree(HOSHINO_SOURCE / 'hoshino', ROOT / 'hoshino', ignore=shutil.ignore_patterns('modules', 'config', '__pycache__'))
    shutil.copytree(HOSHINO_SOURCE / 'hoshino/config_example', ROOT / 'hoshino/config', dirs_exist_ok=True)
    (ROOT/'hoshino/modules').mkdir(exist_ok=True)
    shutil.copytree(HOSHINO_SOURCE/'hoshino/modules/botmanage', ROOT/'hoshino/modules/botmanage')
    cfg = ROOT / 'hoshino/config/__bot__.py'
    config = cfg.read_text(encoding='utf-8')
    cfg.write_text(config[:config.index('MODULES_ON =')] + "MODULES_ON = {'maimai_updata', 'botmanage'}\n", encoding='utf-8')
    target = ROOT / 'hoshino/modules/maimai_updata'
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    for source in (PLUGIN_SOURCE).glob('*.py'):
        shutil.copy2(source, target/source.name)
    shutil.copytree(PLUGIN_SOURCE/'core', target/'core', ignore=shutil.ignore_patterns('__pycache__'))
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT))
    real_expanduser = os.path.expanduser
    def expanduser(path):
        if isinstance(path, str) and path.startswith('~/.hoshino'):
            return str(ROOT / 'hoshino-state') + path[len('~/.hoshino'):]
        return real_expanduser(path)
    os.path.expanduser = expanduser
    if (ROOT/'hoshino-state').exists():
        shutil.rmtree(ROOT/'hoshino-state')
    data = ROOT/'credentials-test-data'
    if data.exists():
        shutil.rmtree(data)
    os.environ['MAIMAI_UPLOAD_DATA_DIR'] = str(data)
    os.environ['MAIMAI_UPLOAD_KEY'] = Fernet.generate_key().decode()
    os.environ['MPLCONFIGDIR'] = str(ROOT/'matplotlib-cache')


async def smoke():
    import hoshino
    import nonebot
    from aiocqhttp.message import MessageSegment
    import qrcode
    from PIL import Image

    bot = hoshino.init()
    await bot.server_app.startup()
    from hoshino.modules.maimai_updata import handlers
    from hoshino.modules.maimai_updata.core.uploader import UploadResult
    router = handlers._registration
    assert router is not None, 'Hoshino did not load actual plugin handlers'
    assert router.main_service.name in hoshino.Service.get_loaded_services()
    assert router.auto_service.name in hoshino.Service.get_loaded_services()
    nonebot.logger.setLevel(logging.WARNING)
    bot.logger.setLevel(logging.WARNING)
    sent, submissions = [], []

    async def send(event, message, **kwargs):
        sent.append(str(message))
        return {'message_id': len(sent)}
    bot.send = send
    async def group_member_info(**kwargs):
        return {'role': 'admin'}
    bot.get_group_member_info = group_member_info
    class MockUpload:
        async def upload(self, code, target, credential):
            submissions.append((code, target, credential))
            return UploadResult(target, 1, 0, None, 'TEST_BACKEND_CONFIRMED')
    router.application.uploader = MockUpload()
    now = [100.]
    router.application.cooldowns.clock = lambda: now[0]
    n = [0]

    async def event(message, kind='private', uid=10001, gid=20001, role='member'):
        n[0] += 1
        now[0] += 10
        start = len(sent)
        payload = dict(time=1, self_id=99999, post_type='message', message_type=kind,
                       sub_type='friend' if kind == 'private' else 'normal', user_id=uid,
                       message_id=n[0], message=message, raw_message='', font=0,
                       sender={'user_id': uid, 'nickname': 'test', 'role': role})
        if kind == 'group':
            payload['group_id'] = gid
        existing_tasks = asyncio.all_tasks()
        await bot._handle_event(payload)
        # NoneBot 1.8 schedules its root message processor with create_task;
        # the more-specific plugin subscriber itself is awaited by EventBus.
        pending = asyncio.all_tasks() - existing_tasks
        if pending:
            await asyncio.wait_for(asyncio.gather(*pending), timeout=3)
        return sent[start:]

    assert any('私聊绑定' in msg for msg in await event('舞萌上传帮助'))
    assert await event('上传成绩 SGWCMAID_ONLY_TEST', 'group') == []
    assert not submissions
    assert any('只能私聊' in msg for msg in await event('水鱼导入token TEST_DISABLED_GROUP_TOKEN', 'group'))
    assert any('已启用服务' in msg for msg in await event('启用 maimai-upload', 'group', uid=10000, role='admin'))
    warning = await event('水鱼导入token NOT_A_REAL_TOKEN', 'group')
    assert len(warning) == 1 and '只能私聊' in warning[0]
    assert 'NOT_A_REAL_TOKEN' not in warning[0]
    assert any('尚未绑定' in msg for msg in await event('上传成绩 SGWCMAID_UNBOUND'))
    assert any('已加密保存' in msg for msg in await event('水鱼导入token TEST_ONLY_TOKEN'))
    assert any('已选择水鱼' in msg for msg in await event('上传源 水鱼'))
    assert await event('上传成绩 SGWCMAID_TEXT_TEST') == ['TEST_BACKEND_CONFIRMED']
    assert submissions == [('SGWCMAID_TEXT_TEST', 'divingfish', 'TEST_ONLY_TOKEN')]
    assert any('近期已提交' in msg for msg in await event('上传成绩 SGWCMAID_TEXT_TEST'))
    assert len(submissions) == 1

    def image(value=None):
        output=io.BytesIO()
        picture=qrcode.make(value) if value else Image.new('RGB', (100, 100), 'white')
        picture.save(output, format='PNG')
        return [{'type': 'image', 'data': {'file': 'base64://' + base64.b64encode(output.getvalue()).decode()}}]

    assert await event(image()) == []
    assert await event(image('SGWCMAID_GROUP_DISABLED_AUTO'), 'group') == []
    assert len(submissions) == 1
    assert any('已启用服务' in msg for msg in await event('启用 maimai-upload-auto', 'group', uid=10000, role='admin'))
    assert await event(image('SGWCMAID_GROUP_IMAGE_TEST'), 'group') == ['TEST_BACKEND_CONFIRMED']
    assert submissions[-1] == ('SGWCMAID_GROUP_IMAGE_TEST', 'divingfish', 'TEST_ONLY_TOKEN')
    assert await event(image('SGWCMAID_PRIVATE_IMAGE_TEST')) == ['TEST_BACKEND_CONFIRMED']
    assert submissions[-1][0] == 'SGWCMAID_PRIVATE_IMAGE_TEST'
    assert await event([{'type':'text','data':{'text':'上传成绩 '}}]+image('SGWCMAID_COMMAND_IMAGE_TEST')) == ['TEST_BACKEND_CONFIRMED']
    assert submissions[-1][0] == 'SGWCMAID_COMMAND_IMAGE_TEST'
    assert any('已禁用服务' in msg for msg in await event('禁用 maimai-upload-auto', 'group', uid=10000, role='admin'))
    assert await event(image('SGWCMAID_DISABLED_AGAIN'), 'group') == []
    assert len(submissions) == 4
    assert any('未识别到有效' in msg for msg in await event([{'type':'text','data':{'text':'上传成绩 '}}]+image()))
    assert any('尚未绑定' in msg for msg in await event('上传源 落雪'))
    assert any('尚未绑定当前目标落雪' in msg for msg in await event('上传成绩 SGWCMAID_LXNS_UNBOUND'))
    assert len(submissions) == 4
    assert any('已加密保存' in msg for msg in await event('落雪个人密钥 TEST_ONLY_LXNS_KEY'))
    assert await event('上传成绩 SGWCMAID_LXNS_TEST') == ['TEST_BACKEND_CONFIRMED']
    assert submissions[-1] == ('SGWCMAID_LXNS_TEST', 'lxns', 'TEST_ONLY_LXNS_KEY')
    assert any('尚未绑定当前目标水鱼' in msg for msg in await event('上传成绩 SGWCMAID_SECOND_USER', uid=10002))
    assert any('已删除' in msg for msg in await event('删除上传凭据'))
    assert await router.application._db('status', '10001') == set()
    assert not router.application.busy and not router.application.active_codes
    await bot.server_app.shutdown()
    from importlib.metadata import version
    report = {
        'status': 'PASS', 'dispatch': 'real aiocqhttp CQHttp._handle_event + NoneBot 1 + target Hoshino.init',
        'events': n[0], 'mock_backend_submissions':len(submissions),
        'loaded_plugins': sorted(p.module.__name__ for p in nonebot.get_loaded_plugins()),
        'real_image_decode':True, 'real_qq_connection':False, 'real_maimai_upload':False,
        'versions':{name:version(name) for name in ['nonebot','aiocqhttp','Quart','matplotlib','maimai-py','aiohttp','Pillow','numpy']},
    }
    if REPORT_PATH is not None:
        REPORT_PATH.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--hoshino-source', required=True, type=Path, help='已克隆目标 HoshinoBot 的目录')
    parser.add_argument('--plugin-source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    HOSHINO_SOURCE = args.hoshino_source.resolve()
    PLUGIN_SOURCE = args.plugin_source.resolve()
    REPORT_PATH = args.report.resolve() if args.report else None
    starting_directory = Path.cwd()
    with tempfile.TemporaryDirectory(prefix='hoshino-smoke-', dir=starting_directory) as directory:
        ROOT = Path(directory)
        try:
            prepare()
            asyncio.run(smoke())
        finally:
            os.chdir(starting_directory)
