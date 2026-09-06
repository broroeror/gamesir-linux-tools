# Releasing

Cutting a release, in order. Most of it is obvious; two steps are here because
they've each been missed once, and neither failure is visible until a user hits it.

Replace `X.Y.Z` throughout.

### 1. Bump the version

`version.py` is the single source of truth — `deadband --doctor` reports it, and a
bug report is worth much less without it.

```sh
sed -i "s/__version__ = '.*'/__version__ = 'X.Y.Z'/" version.py
```

> **Missed once.** v0.2.0 was tagged while the code still said `0.2.0-dev`, so
> everyone on that release reported the wrong version.

### 2. Close the changelog section

Rename `## [Unreleased]` to `## [X.Y.Z] — YYYY-MM-DD`. Its contents become the
release notes in step 5, so it's worth reading once as prose rather than as a diff.

### 3. Update the README

The version line near the top, and the "last tagged snapshot is `vX.Y.Z`" that
follows it.

### 4. Commit, tag, push

```sh
git add -A && git commit -m "release: vX.Y.Z"
git tag -a vX.Y.Z -m "Deadband vX.Y.Z

<a few lines on what this release is>"
git push origin main && git push origin vX.Y.Z
```

### 5. Publish the release

```sh
gh release create vX.Y.Z --title "vX.Y.Z — <short name>" --notes-file notes.md
```

Write the notes from the changelog section rather than from the commit log. Lead
with what changed for the person using it, credit contributors by name, and say
plainly what hasn't been verified on hardware.

### 6. Sync the AUR package

**The one that gets skipped.** The AUR package is a *separate git repository*
containing only its own `PKGBUILD` and `.SRCINFO`. Nothing about merging a PR or
pushing to `main` updates it, and there is no signal when it drifts — so a
dependency added in `packaging/PKGBUILD` silently never reaches the people
installing through `yay`.

```sh
cp packaging/PKGBUILD ../deadband-git/PKGBUILD
cd ../deadband-git
makepkg --printsrcinfo > .SRCINFO          # required: the AUR reads this, not the PKGBUILD
git commit -am "sync PKGBUILD for vX.Y.Z" && git push origin master
```

Check it took (the AUR's own view, not your clone):

```sh
curl -s "https://aur.archlinux.org/rpc/v5/info?arg[]=deadband-git" | python3 -m json.tool | grep -A6 Depends
```

> **Missed once.** v0.3.0 added `libusb` for the G7 Pro transport. The repo's
> PKGBUILD had it; the AUR's didn't, so G7 Pro config would have failed for anyone
> installing the release's headline feature.

### 7. Open the next cycle

```sh
sed -i "s/__version__ = '.*'/__version__ = 'X.Y+1.0-dev'/" version.py
```

Update the README's version line to match. `main` is what the AUR `-git` package
builds, so it shouldn't go on claiming to be the tag.

### Before you announce it

- `python3 smoke_test.py` and `python3 vendors/logitech/offline_checks.py`
- Docs still true? The manual and RESEARCH have both fallen behind the app before.
- No open issues or PRs waiting on a reply.
