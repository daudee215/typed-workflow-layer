"""Create blinded GeoQA Study Harness tasks and compare exported rankings."""

import argparse
from collections import defaultdict
import csv
from itertools import combinations
import json
import math
from pathlib import Path

from examples.workflow_benchmark import admit, load_benchmark
from ranking import rank


def study_definition():
    benchmark, digest = load_benchmark()
    tasks = []
    model = {}
    for case in benchmark["questions"]:
        if not case.get("study"):
            continue
        workflows = [(candidate, admit(case, candidate)) for candidate in case["candidates"]]
        prompt = [case["question"], "", "Rank these workflows for the question as written."]
        for candidate, workflow in workflows:
            text = f"{candidate['id']}. {workflow.expression()}"
            if "predicate" in candidate:
                predicate = candidate["predicate"]
                text += f"  [Constrain: {predicate['operator']} {predicate['value']} dB]"
            prompt.append(text)
        prompt.extend((
            "",
            'Enter JSON rank groups, best first. For example [["W"], ["X", "Y"], ["Z"]].',
            "Put tied candidates in the same group and use each label exactly once.",
        ))
        tasks.append({"task_id": case["id"], "kind": "open", "question": "\n".join(prompt)})
        by_expression = {workflow.expression(): workflow for _, workflow in workflows}
        ranks = {item.expression: item.rank for item in rank(tuple(by_expression.values()))}
        model[case["id"]] = {candidate["id"]: ranks[workflow.expression()]
                             for candidate, workflow in workflows}
    return {"name": f"Workflow benchmark {digest}", "tasks": tasks}, model


def ranking_order(answer: str, labels) -> dict:
    groups = json.loads(answer)
    if (not isinstance(groups, list) or not groups
            or any(not isinstance(group, list) or not group for group in groups)
            or any(not isinstance(label, str) for group in groups for label in group)):
        raise ValueError("an answer must be a list of non-empty rank groups of candidate labels")
    order = {label: index for index, group in enumerate(groups) for label in group}
    if set(order) != set(labels) or sum(map(len, groups)) != len(order):
        raise ValueError("a ranking must contain each candidate label exactly once")
    return order


def compare_orders(first: dict, second: dict) -> dict:
    """Kendall tau-b and the pairs with opposed strict preferences."""
    if first.keys() != second.keys():
        raise ValueError("both rankings must cover the same candidates")
    concordant = discordant = tied_first = tied_second = tied_both = 0
    disagreements = []
    for left, right in combinations(sorted(first), 2):
        a = first[left] - first[right]
        b = second[left] - second[right]
        if a * b > 0:
            concordant += 1
        elif a * b < 0:
            discordant += 1
            disagreements.append({"first_prefers": left if a < 0 else right,
                                  "second_prefers": left if b < 0 else right})
        elif a:
            tied_second += 1
        elif b:
            tied_first += 1
        else:
            tied_both += 1
    ordered = concordant + discordant
    denominator = math.sqrt((ordered + tied_first) * (ordered + tied_second))
    return {
        "tau_b": (concordant - discordant) / denominator if denominator else None,
        "concordant": concordant, "discordant": discordant,
        "tied_first_only": tied_first, "tied_second_only": tied_second, "tied_both": tied_both,
        "disagreements": disagreements,
    }


def evaluate_export(directory: Path) -> dict:
    """Read a consent-filtered Harness export and return a nameless comparison."""
    tasks, model = study_definition()
    exported = json.loads((directory / "tasks.json").read_text(encoding="utf-8"))
    expected = {item["task_id"]: item["question"] for item in tasks["tasks"]}
    actual = {item["task_id"]: item["question"] for item in exported["tasks"]}
    if exported["name"] != tasks["name"] or actual != expected:
        raise ValueError("the exported tasks do not match the frozen study packet")

    ballots = defaultdict(dict)
    with (directory / "responses.csv").open(encoding="utf-8-sig", newline="") as stream:
        for response in csv.DictReader(stream):
            task_id = response["task_id"]
            votes = ballots[response["participant"]]
            if task_id not in model or task_id in votes:
                raise ValueError("the export contains an unexpected or duplicate task response")
            votes[task_id] = ranking_order(response["answer"], model[task_id])
    complete = [votes for _, votes in sorted(ballots.items()) if votes.keys() == model.keys()]
    results = {}
    for task_id, model_order in model.items():
        orders = [votes[task_id] for votes in complete]
        results[task_id] = {
            "model_ranks": model_order,
            "model_vs_analyst": [
                {"analyst": index, **compare_orders(model_order, order)}
                for index, order in enumerate(orders, start=1)
            ],
            "analyst_pairs": [
                {"analysts": [first + 1, second + 1],
                 **compare_orders(orders[first], orders[second])}
                for first, second in combinations(range(len(orders)), 2)
            ],
        }
    return {"study": tasks["name"], "complete_ballots": len(complete),
            "incomplete_ballots": len(ballots) - len(complete), "tasks": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("packet", help="Print blinded tasks as Markdown.")
    commands.add_parser("harness", help="Print GeoQA Study Harness tasks.json.")
    compare = commands.add_parser("compare", help="Compare rankings in a Harness export.")
    compare.add_argument("directory", type=Path)
    args = parser.parse_args()
    if args.command == "compare":
        print(json.dumps(evaluate_export(args.directory), indent=2))
    else:
        tasks, _ = study_definition()
        if args.command == "harness":
            print(json.dumps(tasks, indent=2))
        else:
            print("# Analyst ranking packet\n")
            print(tasks["name"])
            for task in tasks["tasks"]:
                print(f"\n## {task['task_id']}\n\n{task['question']}")


if __name__ == "__main__":
    main()
