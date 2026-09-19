# Release Guide

## Before releasing, always verify locally first

```bash
pytest --cov=xping --cov-report=term-missing
ruff check xping/ --config ruff.toml
ruff format --check xping/ --line-length 100
python -m build && twine check dist/*
```

If any of these fail locally, they will fail in CI too — fix them
*before* tagging, not after.

## Release Steps

```bash
# 1. Bump version in all 4 files (see CONTRIBUTING.md)
OLD=1.3.3; NEW=1.3.4
sed -i "s/version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml
sed -i "s/__version__ = \"$OLD\"/__version__ = \"$NEW\"/" xping/__init__.py
sed -i "s/\"xping $OLD\"/\"xping $NEW\"/" man/xping.1
# update the date in man/xping.1 and add an entry to docs/changelog.md
# and debian/changelog (dch -v "$NEW-1" "..."; dch -r "")

# 2. Verify version consistency (see CONTRIBUTING.md for the script)

# 3. Run the full local check suite above

# 4. Commit, tag, push
git add pyproject.toml xping/__init__.py man/xping.1 \
        docs/changelog.md debian/changelog
git commit -m "chore: release v$NEW"
git tag -a "v$NEW" -m "Release v$NEW"
git push origin main && git push origin "v$NEW"
```

## What happens automatically after the tag push

| Path | Trigger | What it does |
|------|---------|---------------|
| `ci.yml` | every push | tests × 6 environments, lint, version check |
| `release-pypi.yml` | tag `vX.Y.Z` | build → PyPI (OIDC trusted publishing, no token) → GitHub Release |
| `release-launchpad.yml` | tag `vX.Y.Z` | build source package → sign → upload to PPA |
| Snap Store | any push to `main` | built automatically by Snapcraft.io's native GitHub integration — **not** a GitHub Actions workflow. Check status at `snapcraft.io` → your snap → Builds. |

## Versioning

| Change | Bump |
|--------|------|
| Breaking change | MAJOR |
| New command / feature | MINOR |
| Bug fix | PATCH |

## Rollback

```bash
twine yank xping==X.Y.Z --reason "Critical bug"
# Delete the bad PPA build via the Launchpad web UI
# Release a patch immediately
```
