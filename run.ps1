# Pushing this to GitHub

Your repo already has one commit (the README), so the safest route is to clone it
and copy these files in. That avoids force-pushing or fighting unrelated histories.

## Option 1: command line (recommended)

```bash
# 1. clone your empty repo somewhere convenient
git clone https://github.com/AzurianNathan/BDO-Empire-Fusion.git
cd BDO-Empire-Fusion

# 2. copy everything from this bundle into it, EXCEPT any .git folder
#    Windows PowerShell:
#      Copy-Item -Path "C:\path\to\bdo-empire-fused\*" -Destination . -Recurse -Force
#    macOS / Linux:
#      cp -r /path/to/bdo-empire-fused/. .

# 3. check what git will add, confirm no node_modules / .venv / workermanjs
git status
git add -A
git status --short

# 4. commit and push
git commit -m "Fuse Workerman map with bdo-empire optimizer"
git push origin main
```

If `git push` asks for a password, GitHub no longer accepts account passwords.
Create a Personal Access Token (Settings > Developer settings > Personal access
tokens > Fine-grained tokens, with Contents: Read and write on this repo) and use
that as the password. Better still, install GitHub CLI and run `gh auth login`,
which handles it for you.

## Option 2: GitHub Desktop

1. File > Clone repository > BDO-Empire-Fusion.
2. Copy the bundle's files into the cloned folder.
3. GitHub Desktop lists the changes. Write a summary and click Commit to main.
4. Click Push origin.

## Option 3: drag and drop in the browser

Fine for a one-off, but it will not preserve folder structure well and skips the
`.gitignore`, so use it only if the above are not options. On the repo page click
"Add file" > "Upload files" and drag the folders in.

## Before you push, sanity checks

- `git status` should NOT list `workermanjs/`, `node_modules/`, `server/static/`
  or any `.venv/`. The included `.gitignore` covers these.
- The repo should be about 350 KB. If it is tens of megabytes, something ignored
  is being tracked; run `git rm -r --cached <folder>` and commit again.
- `LICENSE` says `Copyright (c) 2026 AzurianNathan`. Change the name if you want
  something different.

## After pushing

Worth adding on the repo page:

- **Topics**: `bdo`, `black-desert-online`, `optimization`, `highs`, `vue`,
  `fastapi`.
- **About**: point it at the README section explaining the Optimize page.
- A short note crediting shrddr and Thell is already in the README; linking their
  repos in your About text is a nice touch too.
