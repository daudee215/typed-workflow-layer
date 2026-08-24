"""The Amsterdam noise example, end to end.

Runs the worked example: the proportion of
area covered by at least 70 dB of noise for each district. The question is
transcribed by hand into the controlled phrasing that request.py accepts, the
phrasing gives a target type and a constraint, synthesis enumerates every
admissible workflow, and each is printed with its conceptual transformation
graph. Two chains are then offered to the type checker and refused.

The geometry at the bottom of this file is toy: axis aligned integer
rectangles, intersected with plain arithmetic. It is here so that the last
section prints numbers that came from somewhere rather than from nowhere. The
library itself contains no executor and no geometry, on purpose. What is being
demonstrated is the typing.
"""

from __future__ import annotations

import ccd
import provenance
import ranking
import request as request_parser
from ccd import CCDType
from cost import CostModel, SourceProfile
from synthesis import Dataset, build_chain, enumerate_workflows, why_rejected

QUESTION = (
    "What is the proportion of area covered by >= 70 dB noise "
    "for each district in Amsterdam?"
)

# Transcribed by hand. There is no natural language step in this package, and
# this line is where a real system would need a controlled natural language or
# a question interface that emits a target type rather than code.
CONTROLLED_PHRASING = "proportion of area where noise >= 70 dB for each district"

SOURCES = (
    # A noise contour map. Region support because the source is contour
    # polygons and not point measurements, so Interpolate will not apply to
    # it. Interval and not ratio because decibels are logarithmic: 80 dB is
    # not twice 40 dB, and declaring it Ratio would licence arithmetic that
    # does not mean anything.
    Dataset("noise", CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)),
    # District boundaries. Nominal because the attribute is a name.
    Dataset("district", CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)),
)

MAX_DEPTH = 4

# The chain a person would write by hand for this question.
INTENDED_CHAIN = (
    ("Constrain", ("noise",)),
    ("Coverage", ("$0", "district")),
    ("Proportion", ("$1",)),
)

# Skips the field to object conversion: it thresholds the noise field and then
# asks for a proportion of it, without ever making the quantity a property of
# a district.
CHAIN_WITHOUT_CONVERSION = (
    ("Constrain", ("noise",)),
    ("Proportion", ("$0",)),
)

# Fails on the support axis rather than the concept axis.
CHAIN_WITH_WRONG_SUPPORT = (("Interpolate", ("noise",)),)

# Toy geometry. Rectangles are (x0, y0, x1, y1) on an integer grid.
DISTRICTS = (
    ("Centrum", (0, 0, 10, 10)),
    ("Zuid", (10, 0, 20, 10)),
    ("Noord", (0, 10, 20, 20)),
)

# Noise contour polygons with their decibel value. Disjoint by construction,
# which the toy coverage step below relies on: it sums intersection areas
# without checking for overlap.
NOISE_CONTOURS = (
    ((0, 0, 6, 5), 75),
    ((6, 0, 10, 5), 68),
    ((10, 0, 14, 10), 72),
    ((0, 10, 20, 14), 55),
    ((14, 14, 20, 20), 80),
)


def heading(number: int, title: str) -> None:
    print()
    print("=" * 74)
    print("{0}. {1}".format(number, title))
    print("=" * 74)


def rectangle_area(rectangle) -> int:
    x0, y0, x1, y1 = rectangle
    return (x1 - x0) * (y1 - y0)


def intersection_area(a, b) -> int:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0
    return width * height


def toy_constrain(contours, operator: str, value: float):
    if operator != ">=":
        raise NotImplementedError(
            "the toy executor implements >= only; the type layer is "
            "indifferent to which comparison is used"
        )
    return tuple(item for item in contours if item[1] >= value)


def toy_coverage(contours, districts):
    covered = {}
    for name, rectangle in districts:
        covered[name] = sum(
            intersection_area(contour, rectangle) for contour, _ in contours
        )
    return covered


def toy_proportion(covered, districts):
    return {
        name: covered[name] / rectangle_area(shape) for name, shape in districts
    }


# Declared metadata about the sources. Nothing here is inferred, and a source
# without a profile is not penalised.
PROFILES = (
    SourceProfile("noise", resolution_m=10.0, year=2024, authority="RIVM"),
    SourceProfile("district", year=2023, authority="CBS"),
)


def ranking_section(workflows) -> None:
    heading(9, "Ranking the {0} that survive".format(len(workflows)))
    model = CostModel(profiles=PROFILES)
    scored = ranking.rank(workflows, model)

    print("Cost is read off the same core concept data type axes the checker")
    print("uses, so it says what a workflow does to the data rather than which")
    print("one somebody preferred. Cheapest first.")
    print()
    for item in scored[:5]:
        print(" ", item)
    print("  ...")
    print(" ", scored[-1])
    print()

    print("The winner as a plan rather than a nested call:")
    print(ranking.plan(scored[0].workflow))
    print()

    print("Why the best beats the worst:")
    print()
    print(ranking.explain(scored[0].workflow, scored[-1].workflow, model))
    print()

    result = ranking.stability(workflows, model)
    print("Sensitivity. Each weight was doubled and halved in turn, {0}".format(
        result["variants"]))
    print("variants in all, and the same workflow won {0} of them.".format(
        result["held"]))
    if result["stable"]:
        print("That makes the winner a claim about the workflows. Had it")
        print("changed, it would have been a claim about the weights, and")
        print("stability() is here so that the difference is measurable")
        print("rather than assumed.")
    print()
    print("agreement() scores any ordering against a human one with Kendall's")
    print("tau, and disagreements() names the pairs where the two part company.")
    print("Those are the honest outputs: a cost model that cannot be shown to")
    print("be wrong is not worth having, and no gold standard of analyst")
    print("preferences has been collected yet, so no tau is reported here.")


def main() -> None:
    print("Typed intermediate layer for geo-analytical question answering")
    print("Worked example: noise exposure by district, Amsterdam")

    heading(1, "The question and the phrasing it was transcribed into")
    print("asked:      " + QUESTION)
    print("controlled: " + CONTROLLED_PHRASING)
    print()
    print("The transcription is manual. This package has no natural language")
    print("component. request.py accepts these phrasings and nothing else:")
    for line in request_parser.GRAMMAR:
        print("  " + line)

    heading(2, "The sources and their core concept data types")
    for source in SOURCES:
        print("  " + str(source))

    heading(3, "The transformation request")
    query = request_parser.parse(CONTROLLED_PHRASING)
    print(query.describe())

    heading(4, "Every admissible workflow, to a depth of {0}".format(MAX_DEPTH))
    print("target: " + str(query.target))
    print()
    print("  {0:>7}{1:>18}{2:>26}".format("depth", "reach the target", "honour the constraint"))
    for depth in range(1, MAX_DEPTH + 1):
        reaching = enumerate_workflows(SOURCES, query.target, max_depth=depth)
        honouring = enumerate_workflows(
            SOURCES,
            query.target,
            max_depth=depth,
            must_use=query.required_transformations(),
        )
        print(
            "  {0:>7}{1:>18}{2:>26}".format(depth, len(reaching), len(honouring))
        )
    workflows = enumerate_workflows(
        SOURCES,
        query.target,
        max_depth=MAX_DEPTH,
        must_use=query.required_transformations(),
    )
    print()
    print("Type validity is necessary and not sufficient. The workflows the")
    print("constraint removes are well typed; they answer a different")
    print("question. The counts above are what a depth bound costs and buys.")
    print("The 24 that remain are ranked in section 9.")
    print()
    print("The {0} admissible workflows, shortest first:".format(len(workflows)))
    for index, workflow in enumerate(workflows, start=1):
        print("  [{0:>2}] {1}".format(index, workflow.expression()))
    print()
    print("The three shortest, with their conceptual transformation graphs:")
    for index, workflow in enumerate(workflows[:3], start=1):
        print()
        print("  [{0}] {1}".format(index, workflow.expression()))
        graph = provenance.from_workflow(workflow, question=QUESTION)
        for line in graph.to_text_tree().splitlines():
            print("      " + line)

    heading(5, "The intended chain, built and checked")
    workflow = build_chain(INTENDED_CHAIN, SOURCES)
    print("chain:  " + workflow.expression())
    print("result: " + str(workflow.result.type))
    print(
        "in the enumerated set: {0}".format(
            workflow.expression() in {item.expression() for item in workflows}
        )
    )
    print()
    print("The step that matters is Coverage. Before it, the quantity is a")
    print("property of the noise field. After it, it is an extensive quantity")
    print("borne by a district, which is the only reason Proportion can then")
    print("normalise it. Every workflow above contains such a step.")

    heading(6, "Two chains the type checker refuses")
    for label, chain in (
        ("skips the field to object conversion", CHAIN_WITHOUT_CONVERSION),
        ("wrong support", CHAIN_WITH_WRONG_SUPPORT),
    ):
        rejection = why_rejected(chain, SOURCES)
        print()
        print("  candidate ({0}):".format(label))
        print(
            "    "
            + " then ".join(
                "{0}({1})".format(name, ", ".join(refs)) for name, refs in chain
            )
        )
        print()
        for line in rejection.explain().splitlines():
            print("    " + line)

    heading(7, "The provenance of the intended workflow, as JSON")
    graph = provenance.from_workflow(workflow, question=QUESTION)
    print(graph.to_json())
    restored = provenance.ConceptualTransformationGraph.from_json(graph.to_json())
    print()
    print("round trips through JSON unchanged: {0}".format(restored == graph))

    heading(8, "The same workflow run over the toy geometry")
    constraint = query.constraints[0]
    kept = toy_constrain(NOISE_CONTOURS, constraint.operator, constraint.value)
    covered = toy_coverage(kept, DISTRICTS)
    shares = toy_proportion(covered, DISTRICTS)
    print("These values come from the rectangles at the top of this file.")
    print("They describe the toy input and say nothing about Amsterdam.")
    print()
    print("  {0:<10}{1:>8}{2:>10}{3:>12}".format("district", "area", "covered", "proportion"))
    for name, shape in DISTRICTS:
        print(
            "  {0:<10}{1:>8}{2:>10}{3:>12.2f}".format(
                name, rectangle_area(shape), covered[name], shares[name]
            )
        )
    print()
    print("Covered area is extensive: the three figures may be summed.")
    print("The proportions are intensive: summing them would mean nothing.")
    print("That distinction is carried by the types, not by the arithmetic.")

    ranking_section(workflows)


if __name__ == "__main__":
    main()
