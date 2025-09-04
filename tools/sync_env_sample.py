from __future__ import annotations
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / ".env.sample"


PATTERNS = [
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z0-9_]+)['\"]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Z0-9_]+)['\"]"),
]


def discover_env_keys() -> set[str]:
    keys: set[str] = set()
    for py in ROOT.rglob("*.py"):
        # skip venvs or caches just in case
        if any(part in {".venv", "__pycache__"} for part in py.parts):
            continue
        try:
            text = py.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for pat in PATTERNS:
            for m in pat.findall(text):
                keys.add(m)
    return keys


def parse_sample(path: Path) -> tuple[list[str], set[str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    present: set[str] = set()
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        k = ln.split("=", 1)[0].strip()
        if k:
            present.add(k)
    return lines, present


def main() -> None:
    found = discover_env_keys()
    lines, present = parse_sample(SAMPLE)

    missing = sorted(k for k in found if k not in present)
    if not missing:
        print(".env.sample is up-to-date")
        return

    # Append missing keys with TODO placeholder
    with SAMPLE.open("a", encoding="utf-8") as f:
        f.write("\n# --- Sync: auto-discovered keys (TODO: set appropriate values) ---\n")
        for k in missing:
            f.write(f"# TODO: set {k}\n{k}=\n")
    print(f"Appended {len(missing)} keys to .env.sample")


if __name__ == "__main__":
    main()
