# 将本次工程导入 GitHub 仓库

本次从目标仓库 `main` 的 `715c1876ea03becb267dbfd816864cfec0712315` 开始，保留历史并在本地 `feat/secure-score-upload` 分支实现。下载包包含可安装的 `maimai_updata/` 和一个 Git format-patch，不含 `.git`、虚拟环境、数据库、真实密钥、临时二维码或参考仓库。

## 有 Git 且希望保留本次提交

在你**自己已授权 GitHub 的本地终端**执行，不需要把凭据发送到聊天：

```bash
git clone https://github.com/AFKsuper/hoshino-maimai-updata.git
cd hoshino-maimai-updata
git switch -c feat/secure-score-upload
# 使用 ZIP 中这个真实补丁的绝对路径：
git am /absolute/path/hoshino-maimai-updata.patch
git diff --check HEAD~1 HEAD
git push -u origin feat/secure-score-upload
```

然后在 GitHub 为该分支创建 PR。若仓库在交付后已新增文件，先审查差异；`git am` 冲突时不要强推或覆盖。可 `git am --abort` 返回原状，再逐文件合并需要的内容。

## 不使用补丁

新建分支后，把 ZIP 中 `maimai_updata/` 的**内部文件**复制到目标仓库根目录（保留 `.git`；遇到用户已有文件先比较）。确认 `README.md`、`handlers.py` 等在仓库根，而不是又嵌套一个模块目录，然后：

```bash
git status --short
git diff --check
git add README.md __init__.py app.py config.py database.py handlers.py core tests docs scripts licenses .github .gitignore .env.example pytest.ini requirements.txt requirements-dev.txt requirements-smoke.txt LICENSE THIRD_PARTY_NOTICES.md
git diff --cached --stat
git commit -m "Add secure Hoshino maimai score upload plugin"
git push -u origin feat/secure-score-upload
```

只用插件无需先推 GitHub：直接按 README 的 ZIP 安装方式把模块放进 HoshinoBot 即可。
