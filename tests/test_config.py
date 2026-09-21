import os
from pathlib import Path

import pytest

from maimai_updata.config import Config


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("MAIMAI_UPLOAD_"):
            monkeypatch.delenv(name)


def test_defaults_are_bounded_and_module_command_is_expected():
    cfg = Config.from_env()
    assert cfg.upload_command == "上传成绩"
    assert cfg.auto_images is True
    assert cfg.max_images == 3
    assert cfg.max_concurrent == 2
    assert cfg.encryption_key == ""
    assert cfg.local_image_roots == ()


def test_every_documented_environment_setting_is_read(monkeypatch, tmp_path):
    settings = {
        "DATA_DIR": str(tmp_path / "data"), "KEY": "test-key-hidden-from-repr",
        "AUTO_IMAGES": "false", "BARE_CODES": "0", "COMMAND": " 成绩导入 ",
        "MAX_IMAGES": "2", "CONCURRENCY": "1", "COOLDOWN": "7",
        "DEDUP_TTL": "180", "TIMEOUT": "90", "IMAGE_TIMEOUT": "8",
        "MAX_IMAGE_BYTES": "4096", "MAX_PIXELS": "5000",
        "LOCAL_IMAGE_ROOTS": os.pathsep.join((str(tmp_path / "a"), str(tmp_path / "b"))),
        "ARCADE_PROXY": "http://example.invalid:8080",
    }
    for name, value in settings.items():
        monkeypatch.setenv("MAIMAI_UPLOAD_" + name, value)
    cfg = Config.from_env()
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.encryption_key == settings["KEY"]
    assert cfg.auto_images is False and cfg.allow_bare_codes is False
    assert cfg.upload_command == "成绩导入"
    assert (cfg.max_images, cfg.max_concurrent, cfg.cooldown) == (2, 1, 7)
    assert (cfg.duplicate_ttl, cfg.upload_timeout, cfg.image_timeout) == (180, 90, 8)
    assert (cfg.max_image_bytes, cfg.max_pixels) == (4096, 5000)
    assert cfg.local_image_roots == (tmp_path / "a", tmp_path / "b")
    assert cfg.arcade_proxy == settings["ARCADE_PROXY"]
    assert settings["KEY"] not in repr(cfg)
    assert settings["ARCADE_PROXY"] not in repr(cfg)


@pytest.mark.parametrize("name,value", [
    ("AUTO_IMAGES", "sometimes"), ("BARE_CODES", "2"), ("COMMAND", " "),
    ("COMMAND", "x" * 33), ("MAX_IMAGES", "0"), ("MAX_IMAGES", "6"),
    ("CONCURRENCY", "0"), ("CONCURRENCY", "9"), ("COOLDOWN", "0"),
    ("DEDUP_TTL", "9"), ("TIMEOUT", "301"), ("IMAGE_TIMEOUT", "0"),
    ("MAX_IMAGE_BYTES", "100"), ("MAX_PIXELS", "999"), ("TIMEOUT", "nan"),
    ("TIMEOUT", "infinity"),
])
def test_unsafe_environment_values_fail_early(monkeypatch, name, value):
    monkeypatch.setenv("MAIMAI_UPLOAD_" + name, value)
    with pytest.raises(ValueError):
        Config.from_env()


def test_dotenv_file_is_not_silently_loaded(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("MAIMAI_UPLOAD_COMMAND=unexpected\n")
    monkeypatch.chdir(tmp_path)
    assert Config.from_env().upload_command == "上传成绩"
