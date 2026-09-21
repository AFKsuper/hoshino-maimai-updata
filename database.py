"""Per-QQ encrypted storage. Credentials are never cached or logged."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken

TARGETS = ('divingfish', 'lxns')


class StorageError(Exception):
    pass


class Database:
    def __init__(self, data_dir, key):
        try:
            self._cipher = Fernet(key.encode('ascii'))
        except Exception:
            raise StorageError('管理员尚未正确配置凭据加密密钥 MAIMAI_UPLOAD_KEY。') from None
        self.directory = Path(data_dir).expanduser()
        if self.directory.is_symlink():
            raise StorageError('数据目录不能是符号链接。')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory.chmod(0o700)
        self.path = self.directory / 'credentials.sqlite3'
        if self.path.is_symlink():
            raise StorageError('数据库不能是符号链接。')
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self._connection() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS users (qq TEXT PRIMARY KEY, target TEXT NOT NULL DEFAULT 'divingfish');
              CREATE TABLE IF NOT EXISTS credentials (qq TEXT NOT NULL, target TEXT NOT NULL, secret BLOB NOT NULL,
                PRIMARY KEY (qq, target));
            ''')

    @contextmanager
    def _connection(self):
        con = sqlite3.connect(str(self.path), timeout=2)
        try:
            con.execute('PRAGMA secure_delete=ON')
            con.execute('PRAGMA journal_mode=DELETE')
            with con:
                yield con
        finally:
            con.close()

    @staticmethod
    def _validate(qq, target=None):
        qq = str(qq)
        if not qq.isdecimal() or len(qq) > 32:
            raise StorageError('无效的 QQ 用户标识。')
        if target is not None and target not in TARGETS:
            raise StorageError('无效上传源。')
        return qq

    def bind(self, qq, target, secret):
        qq = self._validate(qq, target)
        if not isinstance(secret, str) or not secret or len(secret) > 4096 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in secret):
            raise StorageError('凭据为空、含空白或超出安全长度，请重新复制。')
        # Bind ciphertext to both owner and provider, preventing row swaps.
        blob = self._cipher.encrypt((qq + '\0' + target + '\0' + secret).encode())
        with self._connection() as db:
            db.execute('INSERT OR IGNORE INTO users(qq) VALUES (?)', (qq,))
            db.execute('INSERT OR REPLACE INTO credentials VALUES (?,?,?)', (qq, target, blob))

    def get_target(self, qq):
        qq = self._validate(qq)
        with self._connection() as db:
            row = db.execute('SELECT target FROM users WHERE qq=?', (qq,)).fetchone()
        return row[0] if row else 'divingfish'

    def set_target(self, qq, target):
        qq = self._validate(qq, target)
        with self._connection() as db:
            db.execute('INSERT OR REPLACE INTO users VALUES (?,?)', (qq, target))

    def get_secret(self, qq, target):
        qq = self._validate(qq, target)
        with self._connection() as db:
            row = db.execute('SELECT secret FROM credentials WHERE qq=? AND target=?', (qq,target)).fetchone()
        if not row:
            return None
        try:
            owner, provider, secret = self._cipher.decrypt(row[0]).decode().split('\0', 2)
            if owner != qq or provider != target:
                raise InvalidToken
            return secret
        except (InvalidToken, ValueError, UnicodeError):
            raise StorageError('凭据解密失败；请联系管理员恢复原加密密钥，或删除后重新绑定。') from None

    def status(self, qq):
        qq = self._validate(qq)
        with self._connection() as db:
            rows = db.execute('SELECT target FROM credentials WHERE qq=?', (qq,)).fetchall()
        return {row[0] for row in rows}

    def delete(self, qq, target=None):
        qq = self._validate(qq, target)
        with self._connection() as db:
            if target is None:
                db.execute('DELETE FROM credentials WHERE qq=?', (qq,))
                db.execute('DELETE FROM users WHERE qq=?', (qq,))
            else:
                db.execute('DELETE FROM credentials WHERE qq=? AND target=?', (qq, target))
