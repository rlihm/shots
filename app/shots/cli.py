"""shots: standardised website screenshots.

Run `shots` without arguments for the guided menu, or use the direct commands:

  shots new <website> [--name NAME] [--all]   create a project (finds pages)
  shots capture <project> <label>             capture, e.g. label before / after / reference
  shots compare <project> [RUN_A RUN_B]       side by side; default: latest before vs latest after
  shots history <project>                     list all capture runs
  shots list                                  list projects
  shots open <project>                        open the project's screenshot folder
  shots setup                                 install the browser (once, after installing)
"""
from __future__ import annotations

import argparse
import subprocess
import sys

from . import __version__, core

DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def _open(path):
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        print(path)


def _bye():
    print("Cancelled.")
    sys.exit(0)


def _ask(question):
    """Run a questionary prompt; Ctrl-C or Esc ends the program cleanly."""
    answer = question.ask()
    if answer is None:
        _bye()
    return answer


# ------------------------------------------------------------------ shared steps

def run_capture(cfg, label):
    if not cfg["pages"]:
        raise SystemExit(f"Project '{cfg['project']}' has no pages.")
    n, v = len(cfg["pages"]), len(cfg["viewports"])
    print(f"\n{BOLD}{cfg['project']} · {label}{RESET}  {n} pages × {v} devices\n")
    run_dir, m = core.capture(cfg, label)
    total, failed = core.run_summary(m)
    print(f"\nDone: {total - len(failed)}/{total} pages ok" + (f", failed: {', '.join(failed)}" if failed else ""))
    print(f"{DIM}{run_dir}{RESET}")
    return run_dir


def run_compare(cfg, a, b):
    files = core.compare(cfg, a, b)
    if not files:
        print("Nothing to compare: the two runs have no pages in common.")
        return None
    print(f"\n{len(files)} comparison images: {a['label']} vs {b['label']}")
    print(f"{DIM}{files[0].parent}{RESET}")
    return files[0].parent


def find_run(cfg, run_id):
    for r in core.runs(cfg):
        if r["id"] == run_id or r["id"].startswith(run_id):
            return r
    raise SystemExit(f"No run '{run_id}'. See: shots history {cfg['project']}")


# ------------------------------------------------------------------ guided mode

def interactive():
    import questionary
    from questionary import Choice, Separator

    print(f"{BOLD}shots{RESET} {DIM}{__version__}{RESET}\n")
    projects = core.list_projects()
    choices = [Choice("+ New project", "__new")]
    if projects:
        choices.append(Separator())
        width = max(len(p) for p in projects) + 3
        for p in projects:
            choices.append(Choice(f"{p:{width}} {core.status_hint(core.load_project(p))}", p))
    pick = _ask(questionary.select("Project?", choices=choices))
    if pick == "__new":
        cfg = new_project_interactive()
        if cfg and _ask(questionary.confirm("Capture now?", default=True)):
            capture_interactive(cfg)
    else:
        project_menu(core.load_project(pick))


def choose_pages(pages, preselected=None):
    import questionary
    from questionary import Choice

    width = max(len(p["name"]) for p in pages) + 2
    choices = []
    for pg in pages:
        checked = (pg["name"] in preselected) if preselected is not None else not core.is_legal(pg)
        path = core.urlsplit(pg["url"]).path or "/"
        choices.append(Choice(f"{pg['name']:{width}} {path}", value=pg, checked=checked))
    picked = _ask(questionary.checkbox(
        "Which pages?  (space = tick/untick, a = all, enter = done)",
        choices=choices,
        validate=lambda sel: True if sel else "Pick at least one page",
    ))
    return picked


def new_project_interactive():
    import questionary

    url = _ask(questionary.text("Website:", validate=lambda t: bool(t.strip()) or "Enter a domain or URL")).strip()
    name = _ask(questionary.text("Project name:", default=core.suggest_name(url)))
    name = core.slugify(name)
    if core.project_file(name).exists() and not _ask(
        questionary.confirm(f"Project '{name}' exists. Replace its page list?", default=False)
    ):
        _bye()
    print(f"{DIM}Looking for pages...{RESET}")
    try:
        pages, source = core.discover(url)
    except Exception as e:
        raise SystemExit(f"Couldn't open {url}: {str(e).splitlines()[0]}")
    print(f"Found {len(pages)} pages via {source}.")
    picked = choose_pages(pages)
    cfg = {"project": name, "website": url, "pages": picked}
    if core.project_file(name).exists():  # keep settings like captures_dir and hide
        old = core.load_project(name)
        cfg = {**old, **cfg}
    path = core.save_project(cfg)
    print(f"Saved {len(picked)} pages. {DIM}{path}{RESET}")
    return core.load_project(name)


def capture_interactive(cfg):
    import questionary

    suggested = core.suggest_label(cfg)
    options = list(dict.fromkeys([suggested, "before", "after", "reference"])) + ["other..."]
    label = _ask(questionary.select("What is this capture?", choices=options, default=suggested))
    if label == "other...":
        label = _ask(questionary.text("Label (e.g. after-v2, check-2027):"))
    run_dir = run_capture(cfg, label)

    rs = core.runs(cfg)
    pair = core.default_pair(rs)
    if pair and pair[1]["dir"] == run_dir and _ask(questionary.confirm(
        f"Compare with '{pair[0]['label']}' from {core.fmt_date(pair[0]['started'], False)}?", default=True
    )):
        run_compare(cfg, *pair)
    if _ask(questionary.confirm("Open the folder?", default=True)):
        _open(run_dir.parent)


def compare_interactive(cfg):
    import questionary
    from questionary import Choice

    rs = core.runs(cfg)
    if len(rs) < 2:
        print("Need at least two capture runs to compare.")
        return
    pair = core.default_pair(rs)
    choices = [Choice(f"{core.fmt_date(r['started'])}  {r['label']}", r) for r in reversed(rs)]
    a = _ask(questionary.select("Left side (older):", choices=choices,
                                default=next(c for c in choices if c.value is pair[0])))
    b = _ask(questionary.select("Right side (newer):", choices=[c for c in choices if c.value is not a],
                                default=next((c for c in choices if c.value is pair[1] and pair[1] is not a), None)))
    out = run_compare(cfg, a, b)
    if out and _ask(questionary.confirm("Open the comparison folder?", default=True)):
        _open(out)


def edit_pages_interactive(cfg):
    import questionary

    site = cfg.get("website") or cfg["pages"][0]["url"]
    print(f"{DIM}Looking for pages on {site}...{RESET}")
    found, source = core.discover(site)
    current = {pg["name"]: pg for pg in cfg["pages"]}
    # keep pages that weren't found again (e.g. hand-added), discovered ones refresh their URL
    merged = found + [pg for pg in cfg["pages"] if pg["name"] not in {f["name"] for f in found}]
    print(f"Found {len(found)} pages via {source}. Currently selected pages are ticked.")
    picked = choose_pages(merged, preselected=set(current))
    cfg["pages"] = picked
    core.save_project(cfg)
    print(f"Saved {len(picked)} pages.")


def project_menu(cfg):
    import questionary
    from questionary import Choice

    while True:
        suggested = core.suggest_label(cfg)
        has_runs = bool(core.runs(cfg))
        choices = [Choice(f"Capture  ({suggested})", "capture")]
        if len(core.runs(cfg)) >= 2:
            choices.append(Choice("Compare two captures", "compare"))
        if has_runs:
            choices.append(Choice("History", "history"))
        choices += [Choice(f"Edit pages  ({len(cfg['pages'])} selected)", "pages"),
                    Choice("Open folder", "open"), Choice("Quit", "quit")]
        action = _ask(questionary.select(f"{cfg['project']}:", choices=choices))
        if action == "capture":
            capture_interactive(cfg)
            return
        if action == "compare":
            compare_interactive(cfg)
            return
        if action == "history":
            print("\n" + "\n".join(core.history_lines(cfg)) + "\n")
        elif action == "pages":
            edit_pages_interactive(cfg)
            cfg = core.load_project(cfg["project"])
        elif action == "open":
            core.captures_dir(cfg).mkdir(parents=True, exist_ok=True)
            _open(core.captures_dir(cfg))
            return
        else:
            return


# ------------------------------------------------------------------ direct commands

def main(argv=None):
    parser = argparse.ArgumentParser(prog="shots", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"shots {__version__}")
    sub = parser.add_subparsers(dest="cmd")

    p = sub.add_parser("new", help="create a project from a website")
    p.add_argument("website")
    p.add_argument("--name")
    p.add_argument("--all", action="store_true", help="take all pages except legal ones, no questions")
    p = sub.add_parser("capture", help="capture a project")
    p.add_argument("project")
    p.add_argument("label")
    p = sub.add_parser("compare", help="compare two runs")
    p.add_argument("project")
    p.add_argument("runs", nargs="*", metavar="RUN")
    for name in ("history", "open"):
        sub.add_parser(name).add_argument("project")
    sub.add_parser("list")
    sub.add_parser("setup", help="install the browser")

    args = parser.parse_args(argv)
    try:
        if args.cmd is None:
            interactive()
        elif args.cmd == "setup":
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
            core.settings()
            print(f"Ready. Data lives in {core.HOME}")
        elif args.cmd == "list":
            for name in core.list_projects():
                print(f"{name:28} {core.status_hint(core.load_project(name))}")
        elif args.cmd == "new":
            name = core.slugify(args.name or core.suggest_name(args.website))
            pages, source = core.discover(args.website)
            if args.all:
                picked = [pg for pg in pages if not core.is_legal(pg)]
            else:
                print(f"Found {len(pages)} pages via {source}.")
                picked = choose_pages(pages)
            old = core.load_project(name) if core.project_file(name).exists() else {}
            path = core.save_project({**old, "project": name, "website": args.website, "pages": picked})
            print(f"{name}: {len(picked)} pages. {path}")
        elif args.cmd == "capture":
            run_capture(core.load_project(args.project), args.label)
        elif args.cmd == "compare":
            cfg = core.load_project(args.project)
            if len(args.runs) == 2:
                a, b = (find_run(cfg, r) for r in args.runs)
            elif not args.runs:
                pair = core.default_pair(core.runs(cfg))
                if not pair:
                    raise SystemExit("Need at least two capture runs to compare.")
                a, b = pair
            else:
                raise SystemExit("Give two runs, or none for the default pair.")
            run_compare(cfg, a, b)
        elif args.cmd == "history":
            lines = core.history_lines(core.load_project(args.project))
            print("\n".join(lines) if lines else "No captures yet.")
        elif args.cmd == "open":
            cfg = core.load_project(args.project)
            core.captures_dir(cfg).mkdir(parents=True, exist_ok=True)
            _open(core.captures_dir(cfg))
    except KeyboardInterrupt:
        _bye()


if __name__ == "__main__":
    main()
