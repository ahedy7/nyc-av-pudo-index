"""Fix notebook JSON for GitHub: nbformat stream names + optional error stripping."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nbformat.validator import validate


def fix_notebook(path: Path, *, strip_errors: bool = False) -> tuple[int, int]:
    nb = json.loads(path.read_text(encoding="utf-8"))
    schema_fixes = 0
    stripped = 0

    for cell in nb.get("cells", []):
        if strip_errors and cell.get("cell_type") == "code":
            before = len(cell.get("outputs", []))
            cell["outputs"] = [
                o for o in cell.get("outputs", []) if o.get("output_type") != "error"
            ]
            stripped += before - len(cell["outputs"])

        for out in cell.get("outputs", []):
            ot = out.get("output_type")
            if ot == "stream" and "name" not in out:
                out["name"] = "stdout"
                schema_fixes += 1
            if ot in ("execute_result", "display_data") and "metadata" not in out:
                out["metadata"] = {}
                schema_fixes += 1
            if ot == "execute_result" and "execution_count" not in out:
                out["execution_count"] = cell.get("execution_count")
                schema_fixes += 1

    if schema_fixes or stripped:
        path.write_text(json.dumps(nb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    validate(json.loads(path.read_text(encoding="utf-8")))
    return schema_fixes, stripped


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("paths", nargs="*", default=["notebooks"])
    parser.add_argument("--strip-errors", action="store_true")
    args = parser.parse_args()

    paths: list[Path] = []
    for raw in args.paths:
        p = Path(raw)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.ipynb")))
        elif p.suffix == ".ipynb":
            paths.append(p)

    for path in paths:
        schema, stripped = fix_notebook(path, strip_errors=args.strip_errors)
        print(f"{path.name}: {schema} schema fix(es), {stripped} error output(s) removed")


if __name__ == "__main__":
    main()
