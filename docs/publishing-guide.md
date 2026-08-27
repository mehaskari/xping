# راهنمای انتشار xping

## فهرست
- [PyPI](#1--pypi)
- [Launchpad PPA — apt install](#2--launchpad-ppa)
- [Snap Store](#3--snap-store)
- [انتشار همزمان هر سه](#انتشار-همزمان)
- [عیب‌یابی](#عیب‌یابی)

---

## 1 — PyPI

### یک‌بار: Trusted Publishing (بدون نیاز به API token)

1. [pypi.org](https://pypi.org) → xping → Settings → Publishing
2. **Add a new publisher**:
   ```
   Publisher:   GitHub Actions
   Owner:       mehdiaskari
   Repository:  xping
   Workflow:    release-pypi.yml
   Environment: pypi
   ```
3. GitHub repo: **Settings → Environments → New environment** → نام `pypi`

### هر بار: release

```bash
# ورژن check
python3 -c "
import re, sys
files = {
    'pyproject.toml':   (open('pyproject.toml').read(),   r'version = \"(.+?)\"'),
    'xping/__init__.py':(open('xping/__init__.py').read(),r'__version__\s+=\s+\"(.+?)\"'),
    'man/xping.1':      (open('man/xping.1').read(),      r'\"xping ([0-9]+\.[0-9]+\.[0-9]+)\"'),
}
v = {k: re.search(p,t).group(1) for k,(t,p) in files.items()}
assert len(set(v.values())) == 1, f'MISMATCH: {v}'
print('✔', list(v.values())[0])
"

# ساخت
rm -rf dist/ build/ *.egg-info/
python -m build && twine check dist/*

# آپلود دستی (اگه workflow ندارید)
twine upload --repository testpypi dist/*   # تست اول
twine upload dist/*

# تأیید
pip install --upgrade xping && xping --version
```

### روش خودکار

```bash
git tag -a v1.3.1 -m "Release v1.3.1"
git push origin v1.3.1
# GitHub Actions: test → build → PyPI → GitHub Release
```

---

## 2 — Launchpad PPA

کاربر می‌زند:
```bash
sudo add-apt-repository ppa:mehdiaskari/xping
sudo apt update && sudo apt install xping
man xping
```

### مرحله ۱: ساخت حساب Launchpad

1. [launchpad.net](https://launchpad.net) → Register با Ubuntu One
2. Username: `mehdiaskari`

### مرحله ۲: GPG Key

```bash
# اگه ندارید بسازید
gpg --full-generate-key
# نوع: RSA and RSA
# طول: 4096
# نام: Mehdi Askari
# ایمیل: iorganamis@gmail.com

# نمایش ID
gpg --list-secret-keys --keyid-format LONG
# sec   rsa4096/ABCD1234EFGH5678 ...
#                ^^^^^^^^^^^^^^^^  این KEY_ID است

# ارسال به keyserver
gpg --keyserver keyserver.ubuntu.com --send-keys ABCD1234EFGH5678

# در Launchpad: Profile → OpenPGP keys → Import Key → 0xABCD1234EFGH5678
```

### مرحله ۳: ساخت PPA

1. `launchpad.net/~mehdiaskari` → **Create a new PPA**
2. تنظیمات:
   ```
   Name (URL):    xping
   Display Name:  xping — Beautiful CLI Network Diagnostics
   Description:   PPA for xping network diagnostics tool
   ```
3. **Activate**

آدرس PPA: `ppa:mehdiaskari/xping`

### مرحله ۴: آپلود source package

```bash
sudo apt install devscripts debhelper dh-python python3-all \
                 python3-setuptools python3-certifi gnupg dput

VERSION=1.3.1

# ساخت orig tarball
tar \
  --exclude='.git' --exclude='debian' --exclude='dist' \
  --exclude='build' --exclude='*.egg-info' --exclude='.venv' \
  --exclude='__pycache__' \
  -czf "../xping_${VERSION}.orig.tar.gz" .

# ساخت source package
debuild -S -sa -kABCD1234EFGH5678

# بررسی lintian (هدف: صفر error)
lintian --pedantic --tag-display-limit 0 "../xping_${VERSION}-1_source.changes"

# آپلود
dput ppa:mehdiaskari/xping "../xping_${VERSION}-1_source.changes"
```

### مرحله ۵: پیگیری

بعد از `dput`:
- ایمیل تأیید از Launchpad می‌رسد
- صبر کنید ۱۰–۳۰ دقیقه برای build
- `launchpad.net/~mehdiaskari/+archive/ubuntu/xping` → Build Status

### مرحله ۶: تأیید

```bash
sudo add-apt-repository ppa:mehdiaskari/xping
sudo apt update && sudo apt install xping
xping --version   # باید 1.3.1
man xping         # باید man page نشان دهد
```

### چندین Ubuntu series

```bash
# برای Ubuntu 24.04 (Noble)
dch --local ~noble1 --distribution noble "Backport to Ubuntu 24.04 LTS"
dput ppa:mehdiaskari/xping ../xping_1.3.1-1~noble1_source.changes

# برای Ubuntu 22.04 (Jammy)
dch --local ~jammy1 --distribution jammy "Backport to Ubuntu 22.04 LTS"
dput ppa:mehdiaskari/xping ../xping_1.3.1-1~jammy1_source.changes
```

### GitHub Actions secrets

```bash
# LAUNCHPAD_GPG_PRIVATE_KEY
gpg --export-secret-keys --armor ABCD1234EFGH5678

# LAUNCHPAD_GPG_KEY_ID
echo "ABCD1234EFGH5678"
```

در GitHub: **Settings → Secrets → Actions → New repository secret**

---

## 3 — Snap Store

کاربر می‌زند:
```bash
snap install xping
xping --version
man xping
```

### مرحله ۱: ساخت حساب Snap Store

1. [snapcraft.io](https://snapcraft.io) → Register با Ubuntu One
2. **Register a snap name**: `xping`

### مرحله ۲: ابزارها

```bash
sudo snap install snapcraft --classic
sudo snap install lxd
sudo lxd init --auto
snapcraft login
```

### مرحله ۳: build و تست محلی

```bash
cd ~/xping
snapcraft

# تست محلی
sudo snap install xping_1.3.1_amd64.snap --dangerous
xping --version
xping ping 8.8.8.8
man xping
snap remove xping    # بعد از تست
```

### مرحله ۴: انتشار

```bash
snapcraft upload xping_1.3.1_amd64.snap --release stable

# تأیید
snap install xping
xping --version
```

### GitHub Actions secret

```bash
snapcraft export-login \
  --snaps xping \
  --channels stable \
  - > snapcraft-token.txt
# محتوای فایل را در GitHub secret با نام SNAPCRAFT_TOKEN قرار دهید
```

---

## انتشار همزمان

بعد از تنظیمات اولیه، هر release فقط یک مرحله دارد:

```bash
# ۱. Bump ورژن
OLD=1.3.0; NEW=1.3.1
sed -i "s/version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml
sed -i "s/__version__   = \"$OLD\"/__version__   = \"$NEW\"/" xping/__init__.py
sed -i "s/\"xping $OLD\"/\"xping $NEW\"/" man/xping.1
# تاریخ man page و changelog را به‌روز کنید

# ۲. تأیید
python3 -c "
import re, sys
files = {
    'pyproject.toml':   (open('pyproject.toml').read(),   r'version = \"(.+?)\"'),
    'xping/__init__.py':(open('xping/__init__.py').read(),r'__version__\s+=\s+\"(.+?)\"'),
    'man/xping.1':      (open('man/xping.1').read(),      r'\"xping ([0-9]+\.[0-9]+\.[0-9]+)\"'),
}
v = {k: re.search(p,t).group(1) for k,(t,p) in files.items()}
assert len(set(v.values())) == 1
print('✔', list(v.values())[0])
"

# ۳. تست
pytest && ruff check xping/

# ۴. commit و tag
git add pyproject.toml xping/__init__.py man/xping.1 \
        docs/changelog.md debian/changelog
git commit -m "chore: release v$NEW"
git tag -a "v$NEW" -m "Release v$NEW"
git push origin main && git push origin "v$NEW"

# GitHub Actions خودکار:
# ✔ ci.yml             — تست‌ها روی 6 محیط
# ✔ release-pypi.yml   — انتشار روی PyPI
# ✔ release-launchpad.yml — آپلود به PPA
# ✔ release-snap.yml   — انتشار روی Snap Store
```

Snap معمولاً باید جداگانه اجرا شود تا build محلی را تست کنید.

---

## عیب‌یابی

### PyPI

| خطا | علت | راه‌حل |
|-----|-----|--------|
| `400 File already exists` | ورژن تکراری | ورژن را bump کنید |
| `403 Invalid token` | token اشتباه | توکن جدید از pypi.org بسازید |
| `Invalid distribution` | twine check fail | `twine check dist/*` را اجرا کنید |

### Launchpad

| خطا | علت | راه‌حل |
|-----|-----|--------|
| `No acceptable key` | GPG ثبت نشده | `--send-keys` دوباره اجرا کنید |
| `Already uploaded` | ورژن تکراری | `debian/changelog` را bump کنید (`-1` → `-2`) |
| Build FAILED | خطای compile | log را در Launchpad ببینید |
| `lintian: E:` | خطای جدی | `lintian --pedantic` را locally اجرا کنید |

### Snap

| خطا | علت | راه‌حل |
|-----|-----|--------|
| network خطا | plug تعریف نشده | `network` را در `apps.plugs` اضافه کنید |
| `man xping` کار نمی‌کند | man page prime نشده | `override-build` را در snapcraft.yaml بررسی کنید |

### بررسی man page

```bash
# render بدون نصب
groff -man -Tascii man/xping.1 | less

# بررسی syntax
groff -man -Tascii man/xping.1 > /dev/null && echo "OK"

# lintian (برای apt)
lintian --pedantic ../xping_*.changes
```

---

## چک‌لیست نهایی

```
□ ورژن یکسان در pyproject.toml، __init__.py، man/xping.1
□ debian/changelog آپدیت شده
□ python -m build بدون خطا
□ twine check dist/* پاس
□ pytest بدون خطا
□ ruff check xping/ بدون خطا
□ groff -man -Tascii man/xping.1 > /dev/null بدون خطا
□ git tag زده و push شده
```
