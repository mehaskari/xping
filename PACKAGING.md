# Packaging Guide

## PyPI

### Trusted Publishing (once)
1. pypi.org → xping → Settings → Publishing → Add publisher:
   `GitHub / mehdiaskari / xping / release-pypi.yml / pypi`
2. GitHub: Settings → Environments → New → name `pypi`

### Manual
```bash
rm -rf dist/ build/ *.egg-info/
python -m build && twine check dist/*
twine upload --repository testpypi dist/*   # test
twine upload dist/*
```

---

## Launchpad PPA

### Setup (once)
```bash
# GPG key
gpg --full-generate-key   # RSA 4096, Mehdi Askari, iorganamis@gmail.com
gpg --keyserver keyserver.ubuntu.com --send-keys <KEY_ID>
# Launchpad: Profile → OpenPGP keys → Import → 0x<KEY_ID>
# Create PPA: launchpad.net/~mehdiaskari → Create a new PPA → name: xping
```

### Upload
```bash
sudo apt install devscripts debhelper dh-python python3-all \
                 python3-setuptools python3-certifi gnupg dput
VERSION=1.3.1
tar --exclude='.git' --exclude='debian' --exclude='dist' \
    --exclude='build' --exclude='*.egg-info' --exclude='.venv' \
    -czf "../xping_${VERSION}.orig.tar.gz" .
debuild -S -sa -k<KEY_ID>
lintian --pedantic ../xping_${VERSION}-1_source.changes
dput ppa:mehdiaskari/xping ../xping_${VERSION}-1_source.changes
```

### User install
```bash
sudo add-apt-repository ppa:mehdiaskari/xping
sudo apt update && sudo apt install xping
```

### GitHub secrets needed
| Secret | Value |
|--------|-------|
| `LAUNCHPAD_GPG_PRIVATE_KEY` | `gpg --export-secret-keys --armor <KEY_ID>` |
| `LAUNCHPAD_GPG_KEY_ID` | 16-char key ID |

---

## Snap Store

### Setup (once)
```bash
sudo snap install snapcraft --classic
snapcraft login
snapcraft register xping
```

### Build & publish
```bash
snapcraft
sudo snap install xping_1.3.1_amd64.snap --dangerous   # test
snapcraft upload xping_1.3.1_amd64.snap --release stable
```

### GitHub secret
```bash
snapcraft export-login --snaps xping --channels stable - > token.txt
# Add as: SNAPCRAFT_TOKEN
```

---

## Man Page Check
```bash
groff -man -Tascii man/xping.1 > /dev/null && echo OK
lintian --pedantic ../xping_*.changes
```
