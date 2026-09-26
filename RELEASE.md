# Release Guide

A release is: bump the version in a pull request, let CI pass and the PR
merge, then push a `vX.Y.Z` tag on the merge commit. The tag publishes
to PyPI, GitHub Releases and the Launchpad PPA.

## Before releasing, always verify locally first

```bash
pytest --cov=xping --cov-report=term-missing
ruff check xping/ --config ruff.toml
ruff format --check xping/ --line-length 100
python -m build && twine check dist/*
```

If any of these fail locally, they will fail in CI too — fix them
*before* tagging, not after. Also check that the version does not exist
yet: `https://pypi.org/pypi/xping/X.Y.Z/json` must return 404, because
PyPI never lets a version number be reused.

## Release Steps

```bash
# 1. Branch and bump the version in every versioned file (see CONTRIBUTING.md)
git checkout main && git pull --ff-only
OLD=1.4.1; NEW=1.4.2
git checkout -b "release/$NEW"
SED="sed -i"; [ "$(uname)" = Darwin ] && SED="sed -i ''"   # BSD sed on macOS
$SED "s/version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml
$SED "s/__version__ = \"$OLD\"/__version__ = \"$NEW\"/" xping/__init__.py
$SED "s/\"xping $OLD\"/\"xping $NEW\"/" man/xping.1
$SED "s/^version = $OLD$/version = $NEW/" setup.cfg
$SED "s/^version: '$OLD'$/version: '$NEW'/" snap/snapcraft.yaml
# update the .TH date in man/xping.1, turn "## [Unreleased]" entries in
# docs/changelog.md into "## [$NEW] - YYYY-MM-DD", and add a
# debian/changelog entry for noble (dch -v "$NEW-1" "..."; dch -r "")

# 2. Verify version consistency (script in CONTRIBUTING.md) and run the
#    full local check suite above

# 3. Commit, push, open the release PR — it merges itself once CI is green
git add pyproject.toml xping/__init__.py man/xping.1 setup.cfg \
        snap/snapcraft.yaml docs/changelog.md debian/changelog
git commit -m "chore: release v$NEW"
git push -u origin "release/$NEW"
gh pr create --title "chore: release v$NEW" --fill
gh pr merge --auto --merge

# 4. After the PR has merged: tag the merge commit and push the tag
git checkout main && git pull --ff-only
git tag -a "v$NEW" -m "Release v$NEW"
git push origin "v$NEW"
```

Admins can still push the bump straight to `main` (branch protection
does not apply to them), but the PR route runs the full CI first.

## What happens automatically

| Path | Trigger | What it does |
|------|---------|---------------|
| `ci.yml` | every push / PR | tests on Ubuntu + macOS × Python 3.10–3.12 (required), Windows (informational), lint, version check, build |
| `codeql.yml` | every push / PR | CodeQL security analysis |
| `release-pypi.yml` | tag `vX.Y.Z` | build → PyPI (OIDC trusted publishing, no token) → GitHub Release with the `docs/changelog.md` entry as notes |
| `release-launchpad.yml` | tag `vX.Y.Z` | build source package → sign → upload to the PPA; Launchpad then builds it for noble (15–60 min) |
| Snap Store | any push to `main` | built by Snapcraft.io's GitHub integration into the **edge** channel — not a GitHub Actions workflow. Promote a build to **stable** in snapcraft.io → xping → Releases. |

## Versioning

| Change | Bump |
|--------|------|
| Breaking change | MAJOR |
| New command / feature | MINOR |
| Bug fix | PATCH |

## Rollback

- **PyPI:** yank the release on pypi.org → xping → Manage → Releases →
  X.Y.Z → Options → Yank (installers then skip it unless pinned).
- **PPA:** delete the bad upload in the Launchpad web UI.
- **Snap:** move the stable channel back to the previous revision in
  snapcraft.io → xping → Releases.
- Then release a fixed patch version — a yanked version number cannot
  be reused.
