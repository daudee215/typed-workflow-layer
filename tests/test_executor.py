"""Execution, runtime type safety, and the reproducible toy backend."""

import unittest

import ccd
from executor import (
    ExecutionError,
    RuntimeDataset,
    validate_workflow,
    execute,
    union_area,
)
from synthesis import Dataset, Step, Workflow, build_chain


NOISE = Dataset("noise", ccd.CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT))
DISTRICT = Dataset(
    "district", ccd.CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)
)
SOURCES = (NOISE, DISTRICT)
CONTOURS = (
    ((0, 0, 6, 5), 75),
    ((6, 0, 10, 5), 68),
    ((10, 0, 14, 10), 72),
    ((0, 10, 20, 14), 55),
    ((14, 14, 20, 20), 80),
)
DISTRICTS = (
    ("Centrum", (0, 0, 10, 10)),
    ("Zuid", (10, 0, 20, 10)),
    ("Noord", (0, 10, 20, 20)),
)


def workflow():
    return build_chain(
        (
            ("Constrain", ("noise",)),
            ("Coverage", ("$0", "district")),
            ("Proportion", ("$1",)),
        ),
        SOURCES,
    )


def runtime_sources():
    return {
        "noise": RuntimeDataset("noise", NOISE.type, CONTOURS),
        "district": RuntimeDataset("district", DISTRICT.type, DISTRICTS),
    }


class TestExecution(unittest.TestCase):
    def test_valid_workflow_passes_the_execution_boundary_validator(self):
        validate_workflow(workflow())

    def test_forged_output_type_is_refused_before_backend_execution(self):
        valid = workflow()
        forged = Workflow(
            valid.steps[:-1] + (Step(
                "Proportion", ("step2",), "step3",
                ccd.CCDType(ccd.OBJECT, ccd.EXTENSIVE, ccd.REGION_SUPPORT),
            ),),
            valid.sources,
            Dataset("step3", ccd.CCDType(ccd.OBJECT, ccd.EXTENSIVE, ccd.REGION_SUPPORT), "Proportion"),
        )
        with self.assertRaises(ExecutionError) as caught:
            execute(forged, runtime_sources())
        self.assertIn("does not match inferred type", str(caught.exception))

    def test_dangling_workflow_reference_is_refused_before_backend_execution(self):
        valid = workflow()
        forged = Workflow(
            (Step("Constrain", ("missing",), "step1", valid.steps[0].output_type),),
            valid.sources,
            Dataset("step1", valid.steps[0].output_type, "Constrain"),
        )
        with self.assertRaises(ExecutionError) as caught:
            execute(forged, runtime_sources())
        self.assertIn("is not available", str(caught.exception))

    def test_overlapping_rectangles_are_counted_once(self):
        self.assertEqual(
            union_area(((0, 0, 10, 10), (5, 0, 15, 10))), 150.0
        )

    def test_coverage_does_not_double_count_overlapping_contours(self):
        coverage = build_chain(
            (("Coverage", ("noise", "district")),), SOURCES
        )
        supplied = {
            "noise": RuntimeDataset(
                "noise", NOISE.type,
                (((0, 0, 10, 10), 75), ((5, 0, 15, 10), 80)),
            ),
            "district": RuntimeDataset(
                "district", DISTRICT.type, (("zone", (0, 0, 20, 10)),)
            ),
        }
        result = execute(coverage, supplied)
        self.assertEqual(result.value[0].value, 150.0)

    def test_intended_workflow_executes_and_returns_expected_shares(self):
        result = execute(
            workflow(), runtime_sources(),
            parameters={"step1": {"operator": ">=", "value": 70}},
        )
        self.assertEqual(
            {item.object_name: item.value for item in result.value},
            {"Centrum": 0.3, "Zuid": 0.4, "Noord": 0.18},
        )
        self.assertEqual(
            [item.transformation for item in result.records],
            ["Constrain", "Coverage", "Proportion"],
        )
        self.assertEqual(result.output.type, workflow().result.type)

    def test_trace_is_plain_serialisable_data(self):
        result = execute(
            workflow(), runtime_sources(),
            parameters={"step1": {"operator": ">=", "value": 70}},
        )
        payload = result.to_dict()
        self.assertEqual(payload["records"][0]["parameters"]["operator"], "'>='")
        self.assertEqual(payload["records"][1]["inputs"], ["step1", "district"])

    def test_same_run_has_a_stable_fingerprint(self):
        first = execute(
            workflow(), runtime_sources(),
            parameters={"step1": {"operator": ">=", "value": 70}},
        )
        second = execute(
            workflow(), runtime_sources(),
            parameters={"step1": {"operator": ">=", "value": 70}},
        )
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertEqual(len(first.fingerprint), 64)

    def test_changed_parameters_change_the_fingerprint(self):
        first = execute(
            workflow(), runtime_sources(),
            parameters={"step1": {"operator": ">=", "value": 70}},
        )
        second = execute(
            workflow(), runtime_sources(),
            parameters={"step1": {"operator": ">=", "value": 75}},
        )
        self.assertNotEqual(first.fingerprint, second.fingerprint)

    def test_missing_transformation_parameters_fail_at_the_right_step(self):
        with self.assertRaises(ExecutionError) as caught:
            execute(workflow(), runtime_sources())
        self.assertIn("step 1 (Constrain)", str(caught.exception))
        self.assertIn("operator", str(caught.exception))

    def test_runtime_type_is_checked_before_backend_execution(self):
        supplied = runtime_sources()
        supplied["noise"] = RuntimeDataset(
            "noise", ccd.CCDType(ccd.OBJECT, ccd.INTERVAL, ccd.REGION_SUPPORT),
            CONTOURS,
        )
        with self.assertRaises(ExecutionError) as caught:
            execute(workflow(), supplied)
        self.assertIn("runtime value", str(caught.exception))

    def test_malformed_geometry_is_refused_instead_of_silently_fixed(self):
        supplied = runtime_sources()
        supplied["district"] = RuntimeDataset(
            "district", DISTRICT.type, (("bad", (0, 0, 1)),)
        )
        with self.assertRaises(ExecutionError):
            execute(
                workflow(), supplied,
                parameters={"step1": {"operator": ">=", "value": 70}},
            )

    def test_non_finite_geometry_is_refused(self):
        supplied = runtime_sources()
        supplied["district"] = RuntimeDataset(
            "district", DISTRICT.type, (("bad", (0, 0, float("nan"), 1)),)
        )
        with self.assertRaises(ExecutionError) as caught:
            execute(
                workflow(), supplied,
                parameters={"step1": {"operator": ">=", "value": 70}},
            )
        self.assertIn("finite", str(caught.exception))

    def test_duplicate_object_names_are_refused(self):
        supplied = runtime_sources()
        supplied["district"] = RuntimeDataset(
            "district", DISTRICT.type,
            (("same", (0, 0, 10, 10)), ("same", (10, 0, 20, 10))),
        )
        with self.assertRaises(ExecutionError) as caught:
            execute(
                workflow(), supplied,
                parameters={"step1": {"operator": ">=", "value": 70}},
            )
        self.assertIn("duplicate object names", str(caught.exception))

    def test_mapping_key_and_runtime_name_must_agree(self):
        supplied = runtime_sources()
        supplied["noise"] = RuntimeDataset("other", NOISE.type, CONTOURS)
        with self.assertRaises(ExecutionError) as caught:
            execute(workflow(), supplied)
        self.assertIn("disagrees with its name", str(caught.exception))

    def test_parameter_values_must_be_mappings(self):
        with self.assertRaises(ExecutionError) as caught:
            execute(workflow(), runtime_sources(), parameters={"step1": 70})
        self.assertIn("must be a mapping", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
