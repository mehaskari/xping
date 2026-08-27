# Release Guide

## Quick Release

```bash
# 1. Bump version (4 files)
OLD=1.3.0; NEW=1.3.1
sed -i "s/version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml
sed -i "s/__version__   = \"$OLD\"/__version__   = \"$NEW\"/" xping/__init__.py
sed -i "s/\"xping $OLD\"/\"xping $NEW\"/" man/xping.1
# Update date in man/xping.1 and add entry to docs/changelog.md

# 2. Verify
python3 -c "
import re, sys
files = {
    'pyproject.toml':   (open('pyproject.toml').read(),   r'version = \"(.+?)\"'),
    'xping/__init__.py':(open('xping/__init__.py').read(),r'__version__\s+=\s+\"(.+?)\"'),
    'man/xping.1':      (open('man/xping.1').read(),      r'\"xping ([0-9]+\.[0-9]+\.[0-9]+)\"'),
}
v = {k: re.search(p,t).group(1) for k,(t,p) in files.items()}
assert len(set(v.values()))==1, f'MISMATCH: {v}'
print('✔', list(v.values())[0])
"

# 3. Test
pytest && ruff check xping/

# 4. Tag → GitHub Actions does the rest
git add pyproject.toml xping/__init__.py man/xping.1 \
        docs/changelog.md debian/changelog
git commit -m "chore: release v$NEW"
git tag -a "v$NEW" -m "Release v$NEW"
git push origin main && git push origin "v$NEW"
```

GitHub Actions automatically:
- ✔ `ci.yml` — tests on 6 environments
- ✔ `release-pypi.yml` — publishes to PyPI
- ✔ `release-launchpad.yml` — uploads to PPA
- ✔ `release-snap.yml` — publishes to Snap Store
- ✔ GitHub Release with changelog

## Versioning

| Change | Bump | Example |
|--------|------|---------|
| Breaking | MAJOR | 1.x → 2.0.0 |
| New feature | MINOR | 1.2.x → 1.3.0 |
| Bug fix | PATCH | 1.3.0 → 1.3.1 |

## Rollback

```bash
twine yank xping==X.Y.Z --reason "Critical bug"
# Delete PPA build via Launchpad web UI
# Release patch immediately
```
