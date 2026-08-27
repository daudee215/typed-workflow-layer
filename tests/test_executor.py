"""Execution, runtime type safety, and the reproducible toy backend."""

import unittest

import ccd
from executor import (
    ExecutionError,
    RuntimeDataset,
    execute,
)
from synthesis import Dataset, build_chain


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


if __name__ == "__main__":
    unittest.main()
