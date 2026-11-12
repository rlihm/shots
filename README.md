# shots

Standardised website screenshots for references and before/after comparisons.

Type `shots`, answer a few questions, done.

**Standard:** desktop 1440 × 900 at 2× resolution, mobile 390 × 844 at 3× (real iPhone emulation). Every page is captured as `fold` (first screen) and `full` (whole page). Cookie banners and chat widgets are hidden, animations are stopped, and lazy-loaded content is loaded before capture.

## Folder layout

```
~/Toolkit/shots/
  app/          the tool itself. Replace this folder to update
  projects/     one file per project: website, pages, settings
  captures/     screenshots, one folder per project (default location)
  config.yml    global settings
  README.md
```

`projects/`, `captures/` and `config.yml` are created on first use. Updates never touch them.

## One-time setup (Mac)

1. Put this folder at `~/Toolkit/shots`.
2. Remove the macOS download quarantine:
   ```bash
   xattr -dr com.apple.quarantine ~/Toolkit/shots
   ```
3. Install pipx (the installer for command-line tools), if you don't have it:
   ```bash
   brew install pipx
   pipx ensurepath
   ```
   Close and reopen Terminal afterwards.
4. Install shots as a command, then download its browser:
   ```bash
   pipx install -e ~/Toolkit/shots/app
   shots setup
   ```

`shots` now works in any Terminal window, from any folder.

## Using it

```bash
shots
```

**New project:** choose "+ New project", enter the domain (e.g. `elektro-haegler.de`), and confirm the suggested project name. shots finds the pages (from the sitemap, or by following the links), and you tick the ones you want. Legal pages (Impressum, Datenschutz, AGB, …) start unticked. Then capture straight away.

**Existing project:** pick it from the list. The list shows where each project stands, e.g. "before 02.11.2026 · no after yet". The menu suggests the next sensible capture (before → after → after-v2 …). After an "after" capture it offers the comparison with the latest "before".

Other menu options: compare any two captures, show the history, edit the page list (finds pages again and keeps your selection, useful after a relaunch changes the page addresses), open the folder.

**Labels** are free text: `before`, `after`, `after-v2`, `reference`, `check-2027`, … Every capture gets its own folder (`2026-11-02_1140_before`), so nothing is overwritten.

## Direct commands (no questions)

For when you know exactly what you want, or for scheduled runs later:

| Command | What it does |
|---|---|
| `shots new elektro-haegler.de` | Create a project; asks which pages |
| `shots new elektro-haegler.de --all` | Same, but takes all non-legal pages without asking |
| `shots capture elektro-haegler after` | Capture with a label |
| `shots compare elektro-haegler` | Latest before vs latest after |
| `shots compare elektro-haegler RUN_A RUN_B` | Two specific runs (folder names, the start is enough: `2026-11-02_1140`) |
| `shots history elektro-haegler` | All captures of the project |
| `shots list` | All projects with their status |
| `shots open elektro-haegler` | Open the screenshot folder in Finder |

## What you get per project

```
captures/elektro-haegler/
  2026-11-02_1140_before/
    home_desktop_fold.png  home_desktop_full.png  home_mobile_fold.png ...
    run.json              ← record of this run: time, pages, status, titles, settings
  2026-12-15_0912_after/
  compare/
    2026-11-02_1140_before__vs__2026-12-15_0912_after/
      home_desktop_compare.png ...
  history.md              ← timeline with thumbnails, opens in Obsidian
```

The history is built from the `run.json` files in the run folders. Delete a run folder and it disappears from the history, so nothing gets out of sync. If you **move** a run folder somewhere else by hand, shots no longer sees it either.

## Screenshots straight into Google Drive

To keep a project's screenshots in its Drive project folder, add one line to its project file (`projects/elektro-haegler.yml`):

```yaml
captures_dir: ~/Library/CloudStorage/GoogleDrive-<your account>/My Drive/Clients/Elektro Hägler/Screenshots
```

(Find the exact path: open the folder in Finder, right-click it while holding Option → "Copy … as Pathname".)

From then on, shots writes that project's captures straight into Drive, and the history and comparisons keep working. Projects without this line use `captures/` in this folder. The global default is in `config.yml`.

## When something looks wrong

- **A popup is still visible:** most cookie banners are detected automatically. If one gets through, right-click it in your browser → Inspect, copy its id or class, and add it to the project file:
  ```yaml
  hide:
    - ".newsletter-popup"
  ```
- **Images are missing:** the site is slow. Add `wait: 4000` to the project file.
- **A page failed:** it's listed at the end of the run and in the history. Typical causes: the page no longer exists (404) or the site timed out.
- **The house standard** (sizes, resolution): `VIEWPORTS` at the top of `app/shots/core.py`.

## Updating

Replace the `app/` folder with the new one and run the quarantine command from step 2 again. Because of the `-e` install, there's no need to reinstall. If a new version adds new dependencies, run `pipx install -e --force ~/Toolkit/shots/app`.
