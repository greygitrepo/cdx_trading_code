import ast
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "bot" / "configs"


def run_ruff() -> List[Dict[str, object]]:
    """Run ruff to collect unused imports and variables."""
    try:
        proc = subprocess.run(
            ["ruff", str(ROOT), "--select", "F401,F841", "-f", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [{"error": "ruff not installed"}]
    if proc.stdout.strip():
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            return [{"error": "failed to parse ruff output"}]
    return []


def defined_config_keys() -> Set[str]:
    keys: Set[str] = set()
    for path in CONFIG_DIR.glob("*.yaml"):
        try:
            stack: List[tuple[int, str]] = []
            for line in path.read_text().splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if ":" not in line:
                    continue
                indent = len(line) - len(line.lstrip(" "))
                key = line.split(":", 1)[0].strip()
                if key.startswith("-"):
                    continue
                while stack and stack[-1][0] >= indent:
                    stack.pop()
                stack.append((indent, key))
                dotted = ".".join(k for _, k in stack)
                keys.add(dotted)
        except Exception:
            continue
    return keys


def _extract_key(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def used_config_keys() -> Set[str]:
    used: Set[str] = set()
    for path in ROOT.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        for n in ast.walk(tree):
            if isinstance(n, ast.Subscript):
                if (
                    isinstance(n.value, ast.Name)
                    and n.value.id in {"cfg", "config"}
                    and (key := _extract_key(getattr(n.slice, "value", n.slice)))
                ):
                    used.add(key)
            elif (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in {"cfg", "config"}
                and n.args
                and (key := _extract_key(n.args[0]))
            ):
                used.add(key)
    return used


def find_unused_config_keys() -> List[str]:
    defined = defined_config_keys()
    used = used_config_keys()
    return sorted(defined - used)


RISK_TERMS = [
    "fee",
    "fees",
    "commission",
    "taker",
    "maker",
    "slippage",
    "spread",
    "stop",
]


def search_risk_terms() -> Dict[str, bool]:
    result = {term: False for term in RISK_TERMS}
    for path in ROOT.rglob("*.py"):
        try:
            text = path.read_text().lower()
        except Exception:
            continue
        for term in RISK_TERMS:
            if term in text:
                result[term] = True
    return result


def find_dead_code() -> List[Dict[str, object]]:
    dead: List[Dict[str, object]] = []
    for path in ROOT.rglob("*.py"):
        try:
            lines = path.read_text().splitlines()
        except Exception:
            continue
        for idx, line in enumerate(lines, 1):
            if line.strip().startswith("if False"):
                dead.append({"file": str(path), "line": idx})
    return dead


def generate_reports(write: bool = True, output_dir: str = "artifacts/audit") -> Dict[str, object]:
    reports = {
        "ruff": run_ruff(),
        "unused_config_keys": find_unused_config_keys(),
        "risk_terms": search_risk_terms(),
        "dead_code": find_dead_code(),
    }
    if write:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name, data in reports.items():
            with open(out_dir / f"{name}.json", "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
    return reports


def main() -> None:
    generate_reports()


if __name__ == "__main__":
    main()
