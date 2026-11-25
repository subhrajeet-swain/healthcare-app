"""Eval runner. Local by default (CI); --langsmith also runs it as a LangSmith experiment.

python evals/run.py smoke [--langsmith]
"""

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path

DATASETS = Path(__file__).parent / "datasets"

# dataset name -> target under test. Later phases register the real pipeline and chat here.
TARGETS: dict[str, Callable] = {
    "smoke": lambda x: x,
}


def exact_match(output, expected) -> bool:
    return output == expected


def load(name: str) -> list[dict]:
    lines = (DATASETS / f"{name}.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def run_local(name: str) -> bool:
    rows, target = load(name), TARGETS[name]
    failed = [r for r in rows if not exact_match(target(r["input"]), r["expected"])]
    for r in failed:
        print(f"FAIL input={r['input']!r} expected={r['expected']!r}")
    print(f"{name}: {len(rows) - len(failed)}/{len(rows)}")
    return not failed


def run_langsmith(name: str) -> None:
    from langsmith import Client, evaluate

    sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
    from app.tracing import mask

    client = Client(hide_inputs=mask, hide_outputs=mask)
    ds_name = f"healthcare-{name}"
    if not client.has_dataset(dataset_name=ds_name):
        ds = client.create_dataset(ds_name)
        client.create_examples(
            dataset_id=ds.id,
            inputs=[{"input": r["input"]} for r in load(name)],
            outputs=[{"expected": r["expected"]} for r in load(name)],
        )

    def scorer(outputs: dict, reference_outputs: dict) -> bool:
        return exact_match(outputs["output"], reference_outputs["expected"])

    evaluate(
        lambda inputs: {"output": TARGETS[name](inputs["input"])},
        data=ds_name,
        evaluators=[scorer],
        experiment_prefix=name,
        client=client,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("dataset", choices=sorted(TARGETS))
    p.add_argument("--langsmith", action="store_true")
    a = p.parse_args()
    ok = run_local(a.dataset)
    if a.langsmith:
        run_langsmith(a.dataset)
    sys.exit(0 if ok else 1)
