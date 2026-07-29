# Moving this into Claude Code

## 1. Get the files onto your machine

Unzip the bundle somewhere you keep projects, for example:

```
C:\Users\bboyt\Projects\BDO-Empire-Fusion
```

If you already cloned the GitHub repo, copy the files into that folder instead so
git history and the remote stay intact.

## 2. Open it in Claude Code

Desktop app: open the Code tab, then point it at the project folder.

Terminal:

```bash
cd BDO-Empire-Fusion
claude
```

It picks up `CLAUDE.md` automatically. That file carries the context that is not
obvious from the code: why arsha and the official PA API were removed, why the node
router must return Numbers, why a stray 422 usually means a missing model class,
and the theme load-order trap.

## 3. First things worth running there

```bash
python build.py                 # full build, confirms the toolchain works
node tests/router_test.mjs      # router against the real game graph
./run.sh                        # or run.bat
```

Then open http://127.0.0.1:8000, hit reload on the Optimize page, and check the
coverage line reads (N/N). That is the one thing still unverified from my side,
since the dev sandbox cannot reach the market API.

## 4. Pushing

Claude Code uses your existing git credentials, so once the project is in your
clone you can just ask it to commit and push. No token needs to be shared with
anyone.

If git prompts for a password, GitHub no longer accepts account passwords. Use
`gh auth login`, or a fine-grained Personal Access Token with Contents: Read and
write on this repo.

## 5. Good first tasks to hand it

- Run a real solve and sanity-check silver/day against your current empire.
- If price coverage comes up short, switch to blackdesertmarket's category
  endpoints (`/list/{main}/{sub}`) to fetch many items per request instead of ~250
  individual calls. `CLAUDE.md` explains why that is the right fix rather than
  raising concurrency.
- Compare the JS node router's CP against upstream's if you ever obtain the real
  `pkg/`, both are heuristics so small differences are expected.
