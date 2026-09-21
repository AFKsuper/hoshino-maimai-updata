"""Real SQLite/Fernet tests; all credential values are synthetic test fixtures."""
import os
import sqlite3

import pytest
from cryptography.fernet import Fernet

from maimai_updata.database import Database, StorageError


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "private-data", Fernet.generate_key().decode())


def test_credentials_are_isolated_by_qq_and_provider(db):
    db.bind("10001", "divingfish", "unit-test-fish-A")
    db.bind("10001", "lxns", "unit-test-snow-A")
    db.bind("10002", "divingfish", "unit-test-fish-B")
    assert db.get_secret("10001", "divingfish") == "unit-test-fish-A"
    assert db.get_secret("10001", "lxns") == "unit-test-snow-A"
    assert db.get_secret("10002", "divingfish") == "unit-test-fish-B"
    assert db.get_secret("10002", "lxns") is None
    assert db.get_secret("10003", "divingfish") is None
    assert db.status("10001") == {"divingfish", "lxns"}


def test_delete_one_target_or_all_never_deletes_other_user(db):
    for qq in ("10001", "10002"):
        db.bind(qq, "divingfish", "test-only-fish")
        db.bind(qq, "lxns", "test-only-snow")
        db.set_target(qq, "lxns")
    db.delete("10001", "divingfish")
    assert db.status("10001") == {"lxns"}
    assert db.get_target("10001") == "lxns"
    db.delete("10001")
    assert db.status("10001") == set()
    assert db.get_target("10001") == "divingfish"
    assert db.status("10002") == {"divingfish", "lxns"}
    assert db.get_secret("10002", "lxns") == "test-only-snow"
    db.delete("10001")


def test_database_persists_encrypted_data_without_plaintext(tmp_path):
    key = Fernet.generate_key().decode()
    directory = tmp_path / "storage"
    first = Database(directory, key)
    secret = "UNIT-TEST-SYNTHETIC-NOT-A-REAL-TOKEN"
    first.bind("10001", "divingfish", secret)
    first.set_target("10001", "lxns")
    second = Database(directory, key)
    assert second.get_secret("10001", "divingfish") == secret
    assert second.get_target("10001") == "lxns"
    for path in directory.iterdir():
        assert secret.encode() not in path.read_bytes()
        assert key.encode() not in path.read_bytes()
    assert os.stat(directory).st_mode & 0o777 == 0o700
    assert os.stat(first.path).st_mode & 0o777 == 0o600


def test_wrong_key_has_safe_error_and_allows_rebinding(db):
    secret = "unit-test-secret-never-echo"
    db.bind("10001", "divingfish", secret)
    wrong_key = Database(db.directory, Fernet.generate_key().decode())
    with pytest.raises(StorageError) as caught:
        wrong_key.get_secret("10001", "divingfish")
    assert "解密失败" in str(caught.value)
    assert secret not in str(caught.value)
    wrong_key.delete("10001")
    wrong_key.bind("10001", "divingfish", "unit-test-rebound")
    assert wrong_key.get_secret("10001", "divingfish") == "unit-test-rebound"


def test_swapping_encrypted_rows_cannot_cross_owners(db):
    db.bind("10001", "divingfish", "unit-test-A")
    db.bind("10002", "divingfish", "unit-test-B")
    with sqlite3.connect(str(db.path)) as connection:
        cipher = connection.execute("SELECT secret FROM credentials WHERE qq='10001'").fetchone()[0]
        connection.execute("UPDATE credentials SET secret=? WHERE qq='10002'", (cipher,))
    with pytest.raises(StorageError, match="解密失败"):
        db.get_secret("10002", "divingfish")


@pytest.mark.parametrize("secret", ["", "has whitespace", "line\nbreak", "null\0value", "del\x7fvalue", "x" * 4097, None])
def test_bad_credentials_rejected(db, secret):
    with pytest.raises(StorageError):
        db.bind("10001", "divingfish", secret)
    assert db.status("10001") == set()


@pytest.mark.parametrize("qq,target", [("", "divingfish"), ("' OR 1=1", "divingfish"), ("1" * 33, "lxns"), ("10001", "unexpected")])
def test_invalid_identity_or_target_rejected(db, qq, target):
    with pytest.raises(StorageError):
        db.bind(qq, target, "unit-test-value")


@pytest.mark.parametrize("key", ["", "wrong", "密钥"])
def test_invalid_encryption_key_rejected_before_data_creation(tmp_path, key):
    destination = tmp_path / "must-not-exist"
    with pytest.raises(StorageError, match="MAIMAI_UPLOAD_KEY"):
        Database(destination, key)
    assert not destination.exists()


def test_storage_symlink_rejected(tmp_path):
    actual = tmp_path / "actual"
    actual.mkdir()
    link = tmp_path / "link"
    link.symlink_to(actual, target_is_directory=True)
    with pytest.raises(StorageError):
        Database(link, Fernet.generate_key().decode())
    (actual / "credentials.sqlite3").symlink_to(tmp_path / "outside.sqlite3")
    with pytest.raises(StorageError):
        Database(actual, Fernet.generate_key().decode())
