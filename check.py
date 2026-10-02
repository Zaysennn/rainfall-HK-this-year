"""
Does this repository meet the assignment spec?

Run it inside your assignment repo — the folder with README.md in it:

    uv run https://raw.githubusercontent.com/sd5913/pfad/2026/assignments/check.py
    uv run https://raw.githubusercontent.com/sd5913/pfad/2026/assignments/check.py --assignment 2

or, if you have the course repo cloned next to yours:

    uv run ../pfad/assignments/check.py --assignment 2

It prints a checklist and exits with an error if anything on it fails. The same
script runs on GitHub every time you push once you have added the workflow from
`assignments/check.yml` (assignment 1) or `assignments/02-check.yml` (assignment 2)
to your repo — that is where the green tick comes from.

It checks what a script can check: the files are there, the writing is the right
length, the process note says something, the history shows the work happening over
more than one sitting, nothing that does not belong is committed. It cannot tell
whether the essay is any good, or whether the picture says anything. That part is
still a person.

Nothing to install — this uses only what ships with Python.
"""

import argparse
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

# Assignment 1 — an essay.
MIN_WORDS, MAX_WORDS = 500, 1000
# Assignment 2 — a README that documents a picture.
MIN_WORDS_2 = 150

MIN_COMMITS, MIN_DAYS = 3, 2

JUNK = re.compile(r"(^|/)(\.DS_Store|Thumbs\.db|desktop\.ini|\.vscode/|\.idea/|__pycache__/|node_modules/|.*\.docx?$|.*\.pdf$|.*\.zip$)", re.I)
ALLOWED = {"README.md", "PROCESS.md", ".gitignore", ".gitattributes", "LICENSE", "LICENSE.md"}
ALLOWED_DIRS = ("assets/", "images/", "img/", ".github/")

# Assignment 2 additions. Code, a lockfile, the raw data, the pictures.
ALLOWED_2 = ALLOWED | {"pyproject.toml", "uv.lock", "requirements.txt"}
ALLOWED_DIRS_2 = ALLOWED_DIRS + ("data/", "out/", "site/")

# Never belongs in any repo, whatever the assignment.
NEVER = re.compile(r"(^|/)(\.DS_Store|Thumbs\.db|desktop\.ini|\.vscode/|\.idea/|__pycache__/|node_modules/|\.venv/|venv/)", re.I)
# Belongs nowhere except data/, where the raw file is whatever the publisher sent.
DOCUMENTS = re.compile(r".*\.(docx?|pdf|zip)$", re.I)

PICTURES = (".png", ".svg", ".gif", ".mp4", ".jpg", ".jpeg", ".webp")

OK, FAIL, WARN = "  ok  ", "  FAIL", "  note"
failed = 0


def report(status, text):
    global failed
    if status == FAIL:
        failed += 1
    print(f"{status}  {text}")


def words(text):
    """A rough word count that treats markdown as prose and Chinese text fairly."""
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # [text](url) -> text
    text = re.sub(r"<[^>]+>", " ", text)                       # html tags
    text = re.sub(r"[#*_>`|]", " ", text)
    latin = len(text.split())
    cjk = len(re.findall(r"[㐀-鿿]", text))
    return latin + cjk // 2


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def tracked(repo):
    """Every file git knows about, or every file on disk if this is not a repo."""
    listed = git(repo, "ls-files")
    files = listed.split("\n") if listed else [
        str(p.relative_to(repo)) for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts
    ]
    return [f for f in files if f]


# ---------------------------------------------------------------------------
# Assignment 1 — the essay.
# ---------------------------------------------------------------------------


def check_readme(repo):
    path = repo / "README.md"
    if not path.is_file():
        report(FAIL, "README.md is missing at the top level — the essay is the README")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    body = re.split(r"(?im)^#+\s*(references|bibliography|sources|works cited|reference list)\b.*$", text)[0]
    n = words(body)
    if n < 40:
        report(FAIL, f"README.md is a placeholder ({n} words) — the essay goes here")
    elif n < MIN_WORDS:
        report(FAIL, f"README.md is {n} words; the essay is {MIN_WORDS}–{MAX_WORDS} (bibliography not counted)")
    elif n > MAX_WORDS * 1.1:
        report(FAIL, f"README.md is {n} words; the essay is {MIN_WORDS}–{MAX_WORDS} (bibliography not counted)")
    else:
        report(OK, f"README.md: {n} words")
    if re.search(r"(?im)^#+\s*(references|bibliography|sources|works cited|reference list)\b", text):
        report(OK, "README.md has a References section")
    else:
        report(FAIL, "README.md has no References heading — cite what you drew on, APA, at the bottom")
    brackets = len(re.findall(r"\[[^\]\n]{6,}\](?!\()", text))
    if brackets >= 4:
        report(FAIL, f"README.md still has {brackets} [bracketed prompts] — this is an outline, not the essay")
    if not re.search(r"(?m)^#{1,3}\s+\S", text):
        report(WARN, "README.md has no headings — markdown is there to be used")
    if not re.search(r"https?://", text):
        report(WARN, "README.md has no links — if you cite something, link it")


# ---------------------------------------------------------------------------
# Assignment 2 — a picture, and the numbers behind it.
# ---------------------------------------------------------------------------


def check_readme_2(repo):
    path = repo / "README.md"
    if not path.is_file():
        report(FAIL, "README.md is missing at the top level — it says what the picture is")
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    n = words(text)
    if n < 40:
        report(FAIL, f"README.md is a placeholder ({n} words) — the phenomenon, the source, the picture, how to run it")
    elif n < MIN_WORDS_2:
        report(FAIL, f"README.md is {n} words; at least {MIN_WORDS_2} — the phenomenon, the source, the picture, how to run it")
    else:
        report(OK, f"README.md: {n} words")

    embedded = re.search(r"!\[[^\]]*\]\([^)]+\)", text) or re.search(r"(?i)<img\b", text)
    linked = re.search(r"(?i)\]\([^)]+\.(png|svg|gif|mp4|jpe?g|webp)\)", text)
    if embedded or linked:
        report(OK, "README.md shows the picture")
    else:
        report(FAIL, "README.md does not show the picture — embed it: ![what it is](out/your-picture.png)")

    if not re.search(r"https?://", text):
        report(WARN, "README.md has no links — say where the numbers came from, with a link to the source")
    if not re.search(r"(?m)^#{1,3}\s+\S", text):
        report(WARN, "README.md has no headings — markdown is there to be used")


def check_scripts(repo, files):
    """At least one .py, and every .py that imports something says what it needs."""
    scripts = [f for f in files if f.lower().endswith(".py")]
    if not scripts:
        report(FAIL, "no .py file — the picture has to be made by a program you committed")
        return

    # Modules that live in this repo are not dependencies; they are your own files.
    local = {Path(f).stem for f in scripts}
    local |= {f.split("/")[0] for f in files if "/" in f}
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    project = (repo / "pyproject.toml").is_file()

    undeclared, broken = [], []
    for name in scripts:
        path = repo / name
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source)
        except SyntaxError as problem:
            broken.append(f"{name} (line {problem.lineno})")
            continue
        outside = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                outside |= {alias.name.split(".")[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                outside.add(node.module.split(".")[0])
        outside -= stdlib | local | {"__future__"}
        if outside and not re.search(r"(?m)^#\s*///\s*script\b", source) and not project:
            undeclared.append(f"{name} needs {', '.join(sorted(outside)[:3])}")

    if broken:
        report(FAIL, f"does not parse as Python: {', '.join(broken[:3])} — it cannot run, so it cannot be marked")
    if undeclared:
        report(FAIL, f"no dependency block: {'; '.join(undeclared[:3])} — add the "
                     "# /// script block so uv run installs it")
    if not broken and not undeclared:
        report(OK, f"{len(scripts)} script(s), each saying what it needs")


def check_data(repo, files):
    """The raw file you fetched, committed, so the thing runs without the internet."""
    inside = [f for f in files if f.startswith("data/")]
    if not inside:
        report(FAIL, "no data/ folder with a file in it — commit the raw file you fetched, unchanged")
        return
    report(OK, f"data/: {len(inside)} file(s), the numbers travel with the repo")


def check_picture(repo, files):
    pictures = [f for f in files if f.lower().endswith(PICTURES)]
    if not pictures:
        report(FAIL, "no .png, .svg, .gif or .mp4 anywhere — commit the picture your script made")
        return
    report(OK, f"{len(pictures)} picture(s): {', '.join(pictures[:3])}")


# ---------------------------------------------------------------------------
# The same for both.
# ---------------------------------------------------------------------------


def check_process(repo):
    path = repo / "PROCESS.md"
    if not path.is_file():
        near = [p for p in repo.rglob("*") if p.is_file() and p.name.lower() == "process.md" and ".git" not in p.parts]
        if near and near[0].parent == repo:
            # Right file, wrong case. Windows and macOS would not notice; GitHub does.
            report(WARN, f"{near[0].name} should be spelled PROCESS.md exactly — git mv it")
            path = near[0]
        else:
            where = f" (found {near[0].relative_to(repo)} — move it to the top level, exact name)" if near else ""
            report(FAIL, "PROCESS.md is missing" + where)
            return
    text = path.read_text(encoding="utf-8", errors="replace")
    n = words(text)
    none = re.search(r"(?i)\b(did not|didn't|no|without)\b.{0,30}\b(ai|assistant|chatgpt|copilot|llm)\b", text)
    if n < 5:
        report(FAIL, "PROCESS.md is empty — tools used, one thing kept, one thing rejected, and why")
    elif n < 40 and not none:
        report(FAIL, f"PROCESS.md is {n} words — tools used, one thing kept, one thing rejected, and why")
    elif re.search(r"(?i)\b(kept|keep|rejected|reject|discard|threw away|deleted|cut)\b", text) or none:
        report(OK, f"PROCESS.md: {n} words")
    else:
        report(WARN, "PROCESS.md does not say what you kept or rejected — that is the part that carries the marks")


def check_history(repo, what="the essay being written"):
    log = git(repo, "log", "--format=%ad%x09%an%x09%s", "--date=short")
    if log is None:
        report(FAIL, "not a git repository, or git is not installed")
        return
    lines = [ln for ln in log.splitlines() if ln.strip()]
    days = {ln.split("\t")[0] for ln in lines}
    if len(lines) < MIN_COMMITS:
        report(FAIL, f"{len(lines)} commit(s) — the history should show {what}, not pasted")
    elif len(days) < MIN_DAYS:
        report(FAIL, f"{len(lines)} commits, all on one day — spread the work over more than one sitting")
    else:
        report(OK, f"{len(lines)} commits over {len(days)} days")
    vague = [ln for ln in lines if re.fullmatch(r"(?i)(initial commit|first commit|update|update readme\.md|commit|test|.)?", ln.split("\t")[-1].strip())]
    if lines and len(vague) > len(lines) // 2:
        report(WARN, "most commit messages say nothing — 'cut 200 words' beats 'Update README.md'")


def check_files(repo, files, allowed=ALLOWED, allowed_dirs=ALLOWED_DIRS,
                is_junk=None, also_allowed=None,
                beyond="README.md and PROCESS.md",
                extra_hint="the Schotter sketch is a different repo"):
    is_junk = is_junk or JUNK.search
    also_allowed = also_allowed or (lambda f: False)
    junk = [f for f in files if is_junk(f)]
    extra = [f for f in files
             if f.upper() not in {a.upper() for a in allowed}
             and not f.startswith(allowed_dirs)
             and not also_allowed(f)
             and not is_junk(f)]
    if junk:
        report(FAIL, f"files that do not belong in a repo: {', '.join(junk[:4])} — remove them and add them to .gitignore")
    if extra:
        report(WARN, f"{len(extra)} file(s) beyond {beyond}: {', '.join(extra[:4])} — {extra_hint}")
    if not junk and not extra:
        report(OK, "just the files that belong")


def check_visibility():
    private = os.environ.get("ASSIGNMENT_REPO_PRIVATE", "").lower()
    if private == "true":
        report(FAIL, "the repository is private — a private repo cannot be marked")
    elif private == "false":
        report(OK, "the repository is public")


# ---------------------------------------------------------------------------
# The two specs.
# ---------------------------------------------------------------------------


def assignment_one(repo):
    check_readme(repo)
    check_process(repo)
    check_history(repo)
    check_files(repo, tracked(repo))
    check_visibility()
    return "Everything a script can check is in place. Whether the essay is good is up to you."


def assignment_two(repo):
    files = tracked(repo)

    def junk_two(f):
        if NEVER.search(f):
            return True
        if f.startswith("data/"):     # the raw file is whatever they published
            return False
        return bool(DOCUMENTS.match(f))

    check_readme_2(repo)
    check_process(repo)
    check_scripts(repo, files)
    check_data(repo, files)
    check_picture(repo, files)
    check_history(repo, what="the picture being made")
    check_files(repo, files, ALLOWED_2, ALLOWED_DIRS_2, is_junk=junk_two,
                also_allowed=lambda f: f.lower().endswith(".py"),
                beyond="the ones the brief asks for",
                extra_hint="the raw numbers go in data/, the pictures in out/")
    check_visibility()
    return "Everything a script can check is in place. Whether the picture says anything is up to you."


SPECS = {"1": assignment_one, "2": assignment_two}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("path", nargs="?", default=".", help="the repo to check (default: here)")
    ap.add_argument("--assignment", default="1", help="which assignment's spec: 1 or 2")
    args = ap.parse_args()
    spec = SPECS.get(args.assignment)
    if spec is None:
        sys.exit(f"no spec for assignment {args.assignment} — try --assignment 1 or --assignment 2")
    repo = Path(args.path).resolve()
    print(f"Assignment {args.assignment} — {repo.name}\n")
    done = spec(repo)
    print()
    if failed:
        print(f"{failed} thing(s) to fix. Push again when you have, and the check runs again.")
        sys.exit(1)
    print(done)


if __name__ == "__main__":
    main()
