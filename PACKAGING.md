# Packaging Guide

## PyPI

### One-time setup: Trusted Publishing (no API token needed)

1. pypi.org → xping → Settings → Publishing → **Add a new publisher**:
   ```
   Publisher:   GitHub Actions
   Owner:       mehaskari
   Repository:  xping
   Workflow:    release-pypi.yml
   Environment: pypi
   ```
2. GitHub repo → Settings → Environments → New environment → name it `pypi`.

### Release

```bash
git tag -a vX.Y.Z -m "Release vX.Y.Z"
git push origin vX.Y.Z
```
`release-pypi.yml` builds, publishes via OIDC, and creates the GitHub
Release automatically (see [RELEASE.md](RELEASE.md) for the full flow).
The trusted publisher's "Owner" must match the GitHub account that owns
the repository (`mehaskari`), or PyPI rejects the upload.

---

## Launchpad PPA

### One-time setup

**1. GPG key — passphrase or not, both work.**

The signing key can keep a passphrase if you already have one and
don't want to change it. `release-launchpad.yml` handles both cases
through the same mechanism: it writes the passphrase (or an empty
string, if there isn't one) to a private file on the runner and signs
through a small `gpg` wrapper pointed at that file via
`--passphrase-file`, invoked non-interactively with `--batch --no-tty
--pinentry-mode loopback`. No prompt, no terminal needed, either way.

If you don't have a key yet:
```bash
gpg --full-generate-key
# Kind: RSA and RSA, 4096 bits, no expiry
# Name: Mehdi Askari, Email: iorganamis@gmail.com
# Passphrase: whatever you like (or leave empty — both work)
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

**4. Add three GitHub Actions secrets:**

| Secret | Value |
|--------|-------|
| `LAUNCHPAD_GPG_PRIVATE_KEY` | `gpg --export-secret-keys --armor <KEY_ID>` (full output, including the BEGIN/END lines) |
| `LAUNCHPAD_GPG_KEY_ID` | the 16-character key ID |
| `LAUNCHPAD_GPG_PASSPHRASE` | your key's passphrase — **leave this secret empty (create it with no value) if your key has no passphrase**; do not omit the secret entirely, since the workflow always reads it |

### Why the build was failing before

Two separate, unrelated bugs, both fixed and individually verified:

**Bug 1 — `dpkg-checkbuilddeps` failed before the build even started.**
`debian/control` listed `pybuild-plugin-pyproject` in `Build-Depends`,
which doesn't exist on Ubuntu 22.04 (Jammy), the series the PPA
targeted at the time (it now targets noble, 24.04). Fixed by building via the classic `distutils` pybuild system
(a `setup.py` shim + complete `setup.cfg`) instead, which needs no
pyproject-specific plugin.

**Bug 2 — GPG signing failed, in two stages as each was fixed:**
1. First: `gpg: signing failed: Inappropriate ioctl for device` —
   GitHub-hosted runners have no controlling terminal at all, so any
   attempt by gpg to open one for a prompt fails immediately. Fixed
   with `no-tty` + `pinentry-mode loopback` in `gpg.conf`.
2. Then, once that was fixed, a *different* error surfaced for a key
   that has a passphrase: `gpg: Sorry, we are in batchmode - can't get
   input` — batch mode refuses to prompt for anything, including a
   passphrase, unless it's supplied through a non-interactive channel.
   Fixed by writing the passphrase to a private file and signing
   through a `gpg --passphrase-file ...` wrapper, passed to
   `debuild`/`debsign` via its `-p<command>` option.

This was verified end-to-end locally before shipping: a real
passphrase-protected GPG key was generated, and `debsign -p<wrapper>
--clearsign` was run against it exactly the way `debuild -S -sa`
invokes it internally — it signed successfully with no prompt.

### Manual upload (if you ever need to do it by hand)

**The `debian/changelog` distribution field must be a real Ubuntu
series** (`noble`, `jammy`, ...) — never Debian's `unstable`/`testing`.
Launchpad rejects anything else outright with `Unable to find
distroseries: <name>` before the build even queues. This project
targets `noble` (Ubuntu 24.04 LTS); every changelog entry's first line
should read `xping (X.Y.Z-1) noble; urgency=medium`.

```bash
sudo apt install devscripts debhelper dh-python python3-all \
                 python3-setuptools python3-certifi gnupg dput
VERSION=X.Y.Z
tar --exclude='.git' --exclude='debian' --exclude='dist' \
    --exclude='build' --exclude='*.egg-info' --exclude='.venv' \
    -czf "../xping_${VERSION}.orig.tar.gz" .
debuild -S -sa -k<KEY_ID>
lintian --pedantic ../xping_${VERSION}-1_source.changes
dput ppa:mehdiaskari/xping ../xping_${VERSION}-1_source.changes
```

### Shell completion in the package

`debian/rules` (`execute_after_dh_auto_install`) generates completion
for all three shells from the CLI at build time and installs it to:

| Shell | Path |
|-------|------|
| bash | `/usr/share/bash-completion/completions/xping` |
| zsh | `/usr/share/zsh/vendor-completions/_xping` |
| fish | `/usr/share/fish/vendor_completions.d/xping.fish` |

zsh's own `_hosts` completion also claims the command name `xping`;
vendor-completions comes earlier in `$fpath` than zsh's function
directories, and zsh keeps the first definition it finds, so `_xping`
wins. The generated script also calls `compdef` explicitly when sourced.

### User installation
```bash
sudo add-apt-repository ppa:mehdiaskari/xping
sudo apt update && sudo apt install xping
```
The PPA builds for noble only, so it serves Ubuntu 24.04 LTS and
distributions based on it (Linux Mint 22, Pop!_OS 24.04).

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

### Channels

Snapcraft.io builds from `main` land in the **edge** channel. Promote a
tested build to **stable** in snapcraft.io → xping → Releases (drag the
revision to `stable`); `sudo snap install xping` installs stable.

### Shell completion in the snap

The snap declares `completer: xping-completion.bash`; the file is
generated in `override-build`. snapd supports bash completion only.

### Manual build & local test
```bash
sudo snap install snapcraft --classic
snapcraft
sudo snap install xping_X.Y.Z_amd64.snap --dangerous
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
[ ] Version identical in all six files (pyproject.toml, xping/__init__.py,
    man/xping.1, setup.cfg, snap/snapcraft.yaml, debian/changelog)
[ ] debian/changelog has a new noble entry
[ ] docs/changelog.md has a dated entry
[ ] The version is not on PyPI yet (https://pypi.org/pypi/xping/X.Y.Z/json → 404)
```
