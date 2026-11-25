from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from sakshya.generator import DEMO_CASES, KINDS, CaseSpec, generate_case

PACKAGE_DEMO = Path(__file__).resolve().parent / "data" / "demo_cases"


def _generate_demo(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for spec in DEMO_CASES:
        path = generate_case(spec, out)
        print(f"generated {spec.case_id} ({spec.kind}) at {path}")


def _analyse(case_dir: Path) -> None:
    from sakshya.pipeline import analyse, bundle, save_bundle

    data = bundle(analyse(case_dir))
    path = save_bundle(case_dir, data)
    decision = data["decision"]
    print(
        json.dumps(
            {
                "case": data["case"]["id"],
                "decision": decision["label"],
                "score": decision["score"],
                "margin": decision["margin"],
                "bundle": str(path),
            },
            indent=2,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="sakshya", description="Evidence correlation and crime reconstruction engine")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the web workbench")
    serve.add_argument("--host", default="0.0.0.0")
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    demo = sub.add_parser("demo", help="regenerate the bundled demonstration cases")
    demo.add_argument("--out", type=Path, default=PACKAGE_DEMO)
    gen = sub.add_parser("generate", help="generate one synthetic case with an answer key")
    gen.add_argument("kind", choices=KINDS)
    gen.add_argument("--seed", type=int, default=1)
    gen.add_argument("--scale", type=float, default=1.0)
    gen.add_argument("--id", default=None)
    gen.add_argument("--out", type=Path, default=Path("cases"))
    run = sub.add_parser("analyse", help="analyse a case folder and write analysis/bundle.json")
    run.add_argument("case_dir", type=Path)
    sub.add_parser("evaluate", help="run the evaluation suite (see python -m sakshya.evaluation.run --help)")
    args, rest = parser.parse_known_args()
    if args.command == "serve":
        import uvicorn

        uvicorn.run("sakshya.api.app:app", host=args.host, port=args.port, log_level="info")
    elif args.command == "demo":
        _generate_demo(args.out)
    elif args.command == "generate":
        case_id = args.id or f"CASE-{args.kind[:4].upper()}-{args.seed:04d}"
        path = generate_case(CaseSpec(case_id, args.kind, args.seed, args.scale), args.out)
        print(f"generated {case_id} at {path}")
    elif args.command == "analyse":
        _analyse(args.case_dir)
    elif args.command == "evaluate":
        import sys

        from sakshya.evaluation.run import main as evaluate

        sys.argv = ["sakshya.evaluation.run", *rest]
        evaluate()


if __name__ == "__main__":
    main()
