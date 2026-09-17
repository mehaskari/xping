# Packaging Guide

## PyPI

### One-time setup: Trusted Publishing (no API token needed)

1. pypi.org → xping → Settings → Publishing → **Add a new publisher**:
   ```
   Publisher:   GitHub Actions
   Owner:       mehdiaskari
   Repository:  xping
   Workflow:    release-pypi.yml
   Environment: pypi
   ```
2. GitHub repo → Settings → Environments → New environment → name it `pypi`.

### Release

```bash
git tag -a v1.3.4 -m "Release v1.3.4"
git push origin v1.3.4
```
`release-pypi.yml` builds, publishes via OIDC, and creates the GitHub
Release automatically.

---

## Launchpad PPA

### One-time setup

**1. Generate a GPG key *without a passphrase*, specifically for CI.**

This is the standard, well-documented approach for automated package
signing (the encrypted GitHub Secret storing the private key is the
security boundary, not a passphrase gpg would have no way to enter
non-interactively anyway):

```bash
gpg --full-generate-key
# Kind: RSA and RSA, 4096 bits, no expiry
# Name: Mehdi Askari, Email: iorganamis@gmail.com
# When asked for a passphrase: leave it EMPTY
```

If you already have a key **with** a passphrase, strip it:
```bash
gpg --edit-key <KEY_ID>
gpg> passwd
# enter the old passphrase, then press Enter twice for the new one (empty)
gpg> save
```

**2. Publish the key and register it with Launchpad:**
```bash
gpg --list-secret-keys --keyid-format LONG   # note the KEY_ID
gpg --keyserver keyserver.ubuntu.com --send-keys <KEY_ID>
```
Launchpad → your profile → OpenPGP keys → Import Key → `0x<KEY_ID>`,
then decrypt the confirmation email Launchpad sends
(`gpg --decrypt email.txt`) and paste the code back into Launchpad.

**3. Create the PPA:** launchpad.net/~mehdiaskari → Create a new PPA →
name `xping`.

**4. Add two GitHub Actions secrets:**

| Secret | Value |
|--------|-------|
| `LAUNCHPAD_GPG_PRIVATE_KEY` | `gpg --export-secret-keys --armor <KEY_ID>` (full output, including the BEGIN/END lines) |
| `LAUNCHPAD_GPG_KEY_ID` | the 16-character key ID |

### Why the build was failing before

`debsign` (called by `debuild -S -sa`) failed on every run with:
```
gpg: signing failed: Inappropriate ioctl for device
```
GitHub-hosted runners have no controlling terminal at all, so any
attempt by gpg to open one for an interactive passphrase prompt fails
immediately — even with a passphrase-less key, gpg's *default* config
still tries to check for a tty. `release-launchpad.yml` now writes a
`~/.gnupg/gpg.conf` with `batch`, `no-tty`, and `pinentry-mode
loopback`, and a `~/.gnupg/gpg-agent.conf` with `allow-loopback-
pinentry`, before importing the key. Combined with a passphrase-less
key, this signs non-interactively with no prompt at all.

`debian/control` also listed `pybuild-plugin-pyproject` in
`Build-Depends`, which doesn't exist on Ubuntu 22.04 (Jammy) — the
series this PPA targets — so the build failed at
`dpkg-checkbuilddeps` before compiling anything. Fixed by building via
the classic `distutils` pybuild system (a `setup.py` shim + complete
`setup.cfg`) instead, which needs no pyproject-specific plugin.

### Manual upload (if you ever need to do it by hand)

```bash
sudo apt install devscripts debhelper dh-python python3-all \
                 python3-setuptools python3-certifi gnupg dput
VERSION=1.3.4
tar --exclude='.git' --exclude='debian' --exclude='dist' \
    --exclude='build' --exclude='*.egg-info' --exclude='.venv' \
    -czf "../xping_${VERSION}.orig.tar.gz" .
debuild -S -sa -k<KEY_ID>
lintian --pedantic ../xping_${VERSION}-1_source.changes
dput ppa:mehdiaskari/xping ../xping_${VERSION}-1_source.changes
```

### User installation
```bash
sudo add-apt-repository ppa:mehdiaskari/xping
sudo apt update && sudo apt install xping
```

---

## Snap Store

**This project publishes to the Snap Store exclusively through
Snapcraft.io's native GitHub integration** (Snapcraft.io → your snap →
Builds → "Log in with GitHub" → authorize `build-snapcraft-io` →
select the `xping` repository). Every push to `main` triggers a build
there automatically, using `snap/snapcraft.yaml`, with zero GitHub
Actions involvement and zero secrets to manage.

**There is deliberately no `release-snap.yml` GitHub Actions
workflow.** An earlier version of one existed, using
`snapcore/action-publish` with a `SNAPCRAFT_TOKEN` secret — but since
the native integration was already handling every build, that secret
was never configured, and the workflow failed on every single run
with `login_data is empty`. It was a redundant path to the same
destination, manufacturing a permanent false failure signal for
something that already worked. If you ever want the Actions-based
path instead, you would need to disconnect the native GitHub
integration first to avoid double-building, then follow snapcraft's
own `action-build`/`action-publish` documentation with a real
`SNAPCRAFT_TOKEN` from `snapcraft export-login`.

### Manual build & local test
```bash
sudo snap install snapcraft --classic
snapcraft
sudo snap install xping_1.3.4_amd64.snap --dangerous
xping --version
snap remove xping
```

### Check build/publish status
Snapcraft.io → your account → xping → **Builds** tab.

---

## Pre-release checklist

```
[ ] pytest --cov=xping --cov-report=term-missing   passes
[ ] ruff check xping/ --config ruff.toml           passes
[ ] ruff format --check xping/ --line-length 100   passes
[ ] python -m build && twine check dist/*          passes
[ ] Version identical in pyproject.toml, __init__.py, man/xping.1
[ ] debian/changelog has a new entry
[ ] docs/changelog.md has a new entry
```
