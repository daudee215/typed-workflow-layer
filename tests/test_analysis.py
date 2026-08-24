"""Tests for the search analysis, and for the claims it is used to make.

Most of these pin a finding rather than a behaviour. The README and the
analysis output both state numbers about this scenario, and a number in prose
that nothing checks is a number that quietly stops being true. Where a test
asserts an exact figure the docstring says which sentence elsewhere depends
on it.

Depths are kept small on purpose. Depth 5 enumerates 3.4 million candidate
applications and takes about eight seconds, which is fine to run by hand and
not fine in a suite.
"""

import unittest

import analysis
from analysis import SOURCES, TARGET
from synthesis import Restrictions, enumerate_workflows


class TestSoundness(unittest.TestCase):
    """The enumerator against an independent checker.

    why_rejected was written to explain refusals to a person, not to validate
    the search, so it is not the same code path and passing every enumerated
    workflow back through it is a real cross-check.
    """

    def test_every_enumerated_workflow_type_checks(self):
        for depth in (2, 3, 4):
            result = enumerate_workflows(SOURCES, TARGET, max_depth=depth,
                                         max_workflows=100000)
            report = analysis.soundness(result, SOURCES, TARGET)
            self.assertTrue(report.sound, str(report))
            self.assertEqual(report.checked, len(result))

    def test_every_result_actually_satisfies_the_target(self):
        """Soundness is two properties. A well typed workflow answering a
        different question would pass the first and fail this one."""
        result = enumerate_workflows(SOURCES, TARGET, max_depth=3)
        for workflow in result:
            self.assertTrue(TARGET.subsumes(workflow.result.type))

    def test_the_chain_conversion_round_trips(self):
        from synthesis import build_chain
        for workflow in enumerate_workflows(SOURCES, TARGET, max_depth=3):
            rebuilt = build_chain(analysis.to_chain(workflow), SOURCES)
            self.assertEqual(rebuilt.expression(), workflow.expression())


class TestTruncation(unittest.TestCase):
    """The defect the WorkflowSet was added to fix.

    The search used to stop at max_workflows and return a plain list, so a
    capped result was indistinguishable from a complete one.
    """

    def test_a_capped_run_says_it_was_capped(self):
        result = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                     max_workflows=10)
        self.assertEqual(len(result), 10)
        self.assertTrue(result.stats.truncated)
        self.assertFalse(result.complete)

    def test_an_uncapped_run_says_it_was_complete(self):
        result = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                     max_workflows=100000)
        self.assertFalse(result.stats.truncated)
        self.assertTrue(result.complete)

    def test_the_default_cap_is_not_binding_at_the_documented_depth(self):
        """The demo runs at depth 4 with the default cap of 500. If that ever
        starts truncating, the demo is ranking a prefix of the space."""
        result = enumerate_workflows(SOURCES, TARGET, max_depth=4)
        self.assertFalse(result.stats.truncated)

    def test_the_default_cap_would_bind_one_level_deeper(self):
        """Depth 5 finds 1,259 workflows against a default cap of 500, which
        is why the flag has to exist rather than the cap being raised."""
        result = enumerate_workflows(SOURCES, TARGET, max_depth=5)
        self.assertTrue(result.stats.truncated)

    def test_stats_are_recorded_even_on_a_complete_run(self):
        stats = enumerate_workflows(SOURCES, TARGET, max_depth=3).stats
        self.assertGreater(stats.candidates_examined, 0)
        self.assertGreater(stats.type_checks, 0)
        self.assertEqual(stats.workflows_found, 28)


class TestRestrictionsAreMeasured(unittest.TestCase):
    def test_connected_removes_nothing_from_the_result(self):
        """Measured, not assumed. expression() renders only the steps that
        reach the result, so a disconnected workflow always collapses onto the
        expression of its connected core, which is itself enumerated."""
        for depth in (3, 4):
            with_rule = enumerate_workflows(SOURCES, TARGET, max_depth=depth,
                                            max_workflows=100000)
            without = enumerate_workflows(
                SOURCES, TARGET, max_depth=depth, max_workflows=100000,
                restrictions=Restrictions(connected=False))
            self.assertEqual({w.expression() for w in with_rule},
                             {w.expression() for w in without})

    def test_connected_is_subsumed_by_keeping_the_shortest_realisation(self):
        """It used to do one real thing. It no longer does even that.

        Before the deduplication kept the shortest realisation of an
        expression, turning this restriction off left 28 of 176 workflows
        stored carrying a step that fed nothing, so .depth overstated their
        length and cost.py charges length from .depth.

        Keeping the minimum-length realisation removed that too. A workflow
        with a dead step is strictly longer than the same expression without
        it, the shorter one is always reachable by the search, so the shorter
        one always wins the key. The restriction is now provably a no-op on
        both the expression set and the stored objects.

        It is kept as a flag rather than deleted so this stays measurable, and
        so the claim is checked on every run instead of resting on the
        argument above.
        """
        from synthesis import _is_connected
        for rules in (None, Restrictions(connected=False)):
            result = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                         max_workflows=100000,
                                         restrictions=rules)
            dead = [w for w in result if not _is_connected(w.steps)]
            self.assertEqual(dead, [], "dead steps stored with restrictions={0}"
                                       .format(rules))

    def test_the_shortest_realisation_rule_is_what_removes_dead_steps(self):
        """The other half of the claim above, shown rather than asserted.

        Every stored workflow has exactly as many steps as its expression has
        distinct calls. Anything carrying a dead step would exceed that.
        """
        for workflow in enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                            max_workflows=100000):
            self.assertEqual(len(workflow.steps),
                             len(_calls(workflow.expression())),
                             workflow.expression())

    def test_distinct_slots_only_affects_overlay(self):
        """The one catalogue entry taking two slots of the same core concept.
        The comment justifying this restriction used to claim every two-slot
        entry combined different kinds, which is false for Overlay."""
        gained = self._gained(Restrictions(distinct_slots=False), depth=3)
        self.assertTrue(gained)
        for workflow in gained:
            self.assertIn("Overlay(noise, noise)", workflow.expression())

    def test_no_immediate_repeat_removes_multi_level_aggregation(self):
        """The claim in the Restrictions docstring, checked.

        It does not appear at depth 3. Aggregate produces an extensive
        quantity and the target is intensive, so a second Aggregate needs a
        Proportion after it and that only fits at depth 4.
        """
        at_three = self._gained(Restrictions(no_immediate_repeat=False), depth=3)
        self.assertEqual(
            [w for w in at_three if "Aggregate(Aggregate" in w.expression()], [])

        at_four = self._gained(Restrictions(no_immediate_repeat=False), depth=4)
        self.assertTrue(
            [w for w in at_four if "Aggregate(Aggregate" in w.expression()])

    def test_nothing_removed_by_a_restriction_is_unreachable_by_type(self):
        """The completeness claim that matters at the type level.

        Every workflow any restriction removes reaches a type that some kept
        workflow also reaches from the same sources. The restrictions cost
        alternatives, never capability.
        """
        kept = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                   max_workflows=100000)
        signatures = {(str(w.result.type),
                       frozenset(s.name for s in w.sources_consumed()))
                      for w in kept}
        for name in ("connected", "no_immediate_repeat", "distinct_slots"):
            for workflow in self._gained(Restrictions(**{name: False}), depth=4):
                signature = (str(workflow.result.type),
                             frozenset(s.name for s in workflow.sources_consumed()))
                self.assertIn(signature, signatures,
                              "{0} removed a workflow reaching a type nothing "
                              "kept reaches: {1}".format(name, workflow.expression()))

    def _gained(self, rules, depth):
        kept = {w.expression() for w in
                enumerate_workflows(SOURCES, TARGET, max_depth=depth,
                                    max_workflows=100000)}
        relaxed = enumerate_workflows(SOURCES, TARGET, max_depth=depth,
                                      max_workflows=100000, restrictions=rules)
        return [w for w in relaxed if w.expression() not in kept]


class TestGrowth(unittest.TestCase):
    def test_candidates_and_workflows_both_increase_with_depth(self):
        rows = analysis.growth(SOURCES, TARGET, depths=(1, 2, 3, 4))
        for earlier, later in zip(rows, rows[1:]):
            self.assertGreater(later.candidates, earlier.candidates)
            self.assertGreaterEqual(later.workflows, earlier.workflows)

    def test_the_branching_factor_itself_grows(self):
        """Not a fixed base raised to the depth. Each step adds a dataset to
        the pool, and two-slot transformations draw ordered pairs from it, so
        the branching grows with depth rather than staying constant. That is
        why the growth column in the analysis output is not a constant."""
        rows = analysis.growth(SOURCES, TARGET, depths=(2, 3, 4))
        factors = [later.candidates / float(earlier.candidates)
                   for earlier, later in zip(rows, rows[1:])]
        self.assertTrue(all(b > a for a, b in zip(factors, factors[1:])),
                        "expected an increasing growth factor, got {0}".format(factors))

    def test_a_generous_cap_does_not_truncate_the_measurement(self):
        for row in analysis.growth(SOURCES, TARGET, depths=(1, 2, 3, 4)):
            self.assertFalse(row.truncated)


class TestTypeClosure(unittest.TestCase):
    def test_the_type_space_saturates_almost_immediately(self):
        """The finding the depth bound rests on. Five types are reachable and
        nothing new appears after the first round, while the workflow count
        keeps multiplying, so a deeper search returns longer routes to types
        already in hand rather than new capability."""
        rounds, reachable = analysis.type_closure(SOURCES)
        self.assertEqual(len(reachable), 5)
        self.assertEqual(rounds[-1].added, 0)
        self.assertLessEqual(len(rounds), 3)

    def test_the_closure_contains_the_target(self):
        _rounds, reachable = analysis.type_closure(SOURCES)
        self.assertTrue(any(TARGET.subsumes(t) for t in reachable))

    def test_interpolate_cannot_contribute_to_this_question(self):
        """It needs point support and the noise source is region support.
        A fact about this question, not a fault in the catalogue."""
        used, dead = analysis.unreachable_transformations(SOURCES, TARGET)
        self.assertEqual(dead, {"Interpolate"})
        self.assertEqual(len(used), 9)


class TestRankingActuallyOrders(unittest.TestCase):
    def test_the_model_buckets_more_than_it_orders(self):
        """Reported rather than hidden. 176 workflows collapse into 32 scores,
        so a rank of 1 drawn from a tie is not a winner and the analysis says
        so instead of printing a leaderboard."""
        workflows = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                        max_workflows=100000)
        report = analysis.ranking_analysis(workflows)
        self.assertEqual(report.workflows, 176)
        self.assertLess(report.discrimination, 0.25)
        self.assertGreater(report.largest_tie, 1)

    def test_exactly_three_cost_components_are_inert_here(self):
        """support_loss, source and redundancy never vary over this scenario,
        so their weights cannot change the order at any value. Tuning one of
        them to fix a ranking would be wasted effort."""
        workflows = enumerate_workflows(SOURCES, TARGET, max_depth=4,
                                        max_workflows=100000)
        inert = {row.name for row in analysis.component_spread(workflows)
                 if row.inert}
        self.assertEqual(inert, {"support_loss", "source", "redundancy"})

    def test_the_inert_components_are_the_ones_perturbation_cannot_move(self):
        """Two independent measurements that must agree. A component that does
        not vary has to give tau of exactly 1.0 when its weight is perturbed,
        and if it did not, one of the two is wrong."""
        workflows = enumerate_workflows(SOURCES, TARGET, max_depth=3)
        inert = {row.name for row in analysis.component_spread(workflows)
                 if row.inert}
        for row in analysis.weight_sensitivity(workflows):
            name = row.weight.rsplit(" ", 1)[0]
            if name in inert:
                self.assertEqual(row.tau, 1.0,
                                 "{0} is inert but perturbing it moved the "
                                 "order".format(name))

    def test_the_ordering_is_robust_to_a_quarter_turn_on_any_one_weight(self):
        workflows = enumerate_workflows(SOURCES, TARGET, max_depth=3)
        for row in analysis.weight_sensitivity(workflows):
            self.assertGreater(row.tau, 0.9,
                               "{0} reordered the result".format(row.weight))


if __name__ == "__main__":
    unittest.main()


def _calls(expression):
    """Every distinct non-source call in an expression.

    The minimum number of steps a workflow with that expression can have, so
    comparing it against len(workflow.steps) detects both a dead step and a
    subexpression computed twice.
    """
    found, depth, start = set(), 0, 0
    for index, character in enumerate(expression):
        if character == "(":
            if depth == 0:
                start = index
                while start > 0 and (expression[start - 1].isalnum()
                                     or expression[start - 1] == "_"):
                    start -= 1
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                span = expression[start:index + 1]
                found.add(span)
                found |= _calls(span[span.index("(") + 1:-1])
    return found
