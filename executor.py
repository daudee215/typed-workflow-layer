"""Execution of typed workflows over a small, deterministic geometry backend.

The type layer deliberately does not pretend to be a GIS. This module adds the
missing seam between a synthesised workflow and an executable implementation:
runtime values carry their CCD type, operations are provided by a backend, and
every step produces a trace that can be audited or compared with a reference.

The default backend uses axis-aligned rectangles and standard-library data
structures. It is useful for tests, reproducible examples, and a research
prototype because it has no hidden CRS or geometry-library assumptions. A real
GIS adapter can implement the same ``Backend.run`` contract without changing
the ontology, search, or provenance layers.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from ccd import CCDType
from synthesis import Dataset, Step, Workflow

Rectangle = tuple[float, float, float, float]


@dataclass(frozen=True)
class FieldRecord:
    """A field value attached to a rectangular geometry."""

    geometry: Rectangle
    value: Any
    id: str = ""


@dataclass(frozen=True)
class ObjectRecord:
    """A named rectangular object used as a spatial grouping unit."""

    name: str
    geometry: Rectangle


@dataclass(frozen=True)
class ObjectMeasure:
    """A value attached to an object, with its denominator when known."""

    object_name: str
    value: Optional[float]
    denominator: float


@dataclass(frozen=True)
class RuntimeDataset:
    """A named runtime value with the type promised by the workflow."""

    name: str
    type: CCDType
    value: Any
    metadata: tuple = ()


@dataclass(frozen=True)
class ExecutionRecord:
    """One auditable operation invocation."""

    step_index: int
    transformation: str
    inputs: tuple
    output: str
    input_types: tuple
    output_type: CCDType
    parameters: tuple = ()

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "transformation": self.transformation,
            "inputs": list(self.inputs),
            "output": self.output,
            "input_types": list(self.input_types),
            "output_type": self.output_type.serialise(),
            "parameters": {key: value for key, value in self.parameters},
        }


@dataclass(frozen=True)
class ExecutionResult:
    """The final runtime value and the complete execution trace."""

    output: RuntimeDataset
    records: tuple

    @property
    def value(self) -> Any:
        """Convenience access to the final payload."""
        return self.output.value

    def to_dict(self) -> dict:
        return {
            "output": {
                "name": self.output.name,
                "type": self.output.type.serialise(),
                "metadata": dict(self.output.metadata),
            },
            "records": [record.to_dict() for record in self.records],
        }


class ExecutionError(RuntimeError):
    """A structured failure while binding or running a workflow step."""

    def __init__(self, message: str, step_index: Optional[int] = None,
                 transformation: Optional[str] = None):
        self.step_index = step_index
        self.transformation = transformation
        prefix = ""
        if step_index is not None:
            prefix = "step {0}".format(step_index + 1)
            if transformation:
                prefix += " ({0})".format(transformation)
            prefix += ": "
        super().__init__(prefix + message)


class Backend:
    """Backend contract used by :func:`execute`."""

    def run(self, transformation: str, inputs: Sequence[Any],
            parameters: Mapping[str, Any]) -> Any:
        raise NotImplementedError


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExecutionError("{0} must be numeric, got {1!r}".format(label, value))
    return float(value)


def _rectangle(value: Any, label: str) -> Rectangle:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ExecutionError("{0} must be (x0, y0, x1, y1)".format(label))
    result = tuple(_number(item, label) for item in value)
    if result[2] < result[0] or result[3] < result[1]:
        raise ExecutionError("{0} has inverted bounds".format(label))
    return result  # type: ignore[return-value]


def rectangle_area(rectangle: Rectangle) -> float:
    """Return the non-negative area of a validated rectangle."""
    return max(0.0, rectangle[2] - rectangle[0]) * max(
        0.0, rectangle[3] - rectangle[1]
    )


def intersection_area(a: Rectangle, b: Rectangle) -> float:
    """Return the area of the intersection of two rectangles."""
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0.0, min(a[3], b[3]) - max(a[1], b[1])
    )


def _fields(value: Any) -> tuple[FieldRecord, ...]:
    if not isinstance(value, (tuple, list)):
        raise ExecutionError("field payload must be a sequence of records")
    found = []
    for index, item in enumerate(value):
        if isinstance(item, FieldRecord):
            found.append(FieldRecord(_rectangle(item.geometry, "field geometry"),
                                     item.value, item.id))
            continue
        if not isinstance(item, (tuple, list)) or len(item) not in (2, 3):
            raise ExecutionError(
                "field record {0} must be (rectangle, value[, id])".format(index)
            )
        found.append(FieldRecord(
            _rectangle(item[0], "field geometry"), item[1],
            str(item[2]) if len(item) == 3 else "field{0}".format(index),
        ))
    return tuple(found)


def _objects(value: Any) -> tuple[ObjectRecord, ...]:
    if not isinstance(value, (tuple, list)):
        raise ExecutionError("object payload must be a sequence of records")
    found = []
    for index, item in enumerate(value):
        if isinstance(item, ObjectRecord):
            found.append(ObjectRecord(
                str(item.name), _rectangle(item.geometry, "object geometry")
            ))
            continue
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ExecutionError(
                "object record {0} must be (name, rectangle)".format(index)
            )
        found.append(ObjectRecord(
            str(item[0]), _rectangle(item[1], "object geometry")
        ))
    return tuple(found)


def _measures(value: Any) -> tuple[ObjectMeasure, ...]:
    if not isinstance(value, (tuple, list)):
        raise ExecutionError("object measure payload must be a sequence")
    found = []
    for index, item in enumerate(value):
        if isinstance(item, ObjectMeasure):
            found.append(item)
            continue
        if not isinstance(item, (tuple, list)) or len(item) != 3:
            raise ExecutionError(
                "measure {0} must be (object name, value, denominator)".format(index)
            )
        value_number = None if item[1] is None else _number(item[1], "measure value")
        denominator = _number(item[2], "measure denominator")
        found.append(ObjectMeasure(str(item[0]), value_number, denominator))
    return tuple(found)


def _comparison(name: str) -> Callable[[float, float], bool]:
    aliases = {"at least": ">=", "at most": "<=", "above": ">", "below": "<"}
    name = aliases.get(name, name)
    operations = {
        ">=": operator.ge,
        ">": operator.gt,
        "<=": operator.le,
        "<": operator.lt,
        "==": operator.eq,
        "=": operator.eq,
    }
    try:
        return operations[name]
    except KeyError:
        raise ExecutionError(
            "unsupported comparison {0!r}; use >=, >, <=, < or ==".format(name)
        ) from None


class RectangularBackend(Backend):
    """A deterministic backend for rectangle-based research examples."""

    def run(self, transformation: str, inputs: Sequence[Any],
            parameters: Mapping[str, Any]) -> Any:
        handlers = {
            "Constrain": self._constrain,
            "Clip": self._clip,
            "Coverage": self._coverage,
            "ZonalStatistics": self._zonal_statistics,
            "Aggregate": self._aggregate,
            "Proportion": self._proportion,
            "Reclassify": self._reclassify,
            "Buffer": self._buffer,
            "Overlay": self._overlay,
        }
        try:
            handler = handlers[transformation]
        except KeyError:
            raise ExecutionError(
                "the rectangular backend does not implement {0}".format(
                    transformation
                )
            ) from None
        return handler(inputs, parameters)

    def _constrain(self, inputs, parameters):
        if len(inputs) != 1:
            raise ExecutionError("Constrain expects one input")
        try:
            comparison = _comparison(str(parameters["operator"]))
            threshold = _number(parameters["value"], "constraint value")
        except KeyError as error:
            raise ExecutionError(
                "Constrain requires parameters 'operator' and 'value'"
            ) from error
        result = []
        for record in _fields(inputs[0]):
            numeric = _number(record.value, "constrained field value")
            if comparison(numeric, threshold):
                result.append(record)
        return tuple(result)

    def _clip(self, inputs, _parameters):
        fields, objects = _fields(inputs[0]), _objects(inputs[1])
        result = []
        for field in fields:
            for obj in objects:
                if intersection_area(field.geometry, obj.geometry) <= 0:
                    continue
                x0 = max(field.geometry[0], obj.geometry[0])
                y0 = max(field.geometry[1], obj.geometry[1])
                x1 = min(field.geometry[2], obj.geometry[2])
                y1 = min(field.geometry[3], obj.geometry[3])
                result.append(FieldRecord(
                    (x0, y0, x1, y1), field.value,
                    "{0}|{1}".format(field.id, obj.name),
                ))
        return tuple(result)

    def _coverage(self, inputs, _parameters):
        fields, objects = _fields(inputs[0]), _objects(inputs[1])
        return tuple(ObjectMeasure(
            obj.name,
            sum(intersection_area(field.geometry, obj.geometry)
                for field in fields),
            rectangle_area(obj.geometry),
        ) for obj in objects)

    def _zonal_statistics(self, inputs, _parameters):
        fields, objects = _fields(inputs[0]), _objects(inputs[1])
        result = []
        for obj in objects:
            weighted = 0.0
            covered = 0.0
            for field in fields:
                area = intersection_area(field.geometry, obj.geometry)
                if area:
                    weighted += _number(field.value, "zonal field value") * area
                    covered += area
            result.append(ObjectMeasure(
                obj.name, weighted / covered if covered else None,
                rectangle_area(obj.geometry),
            ))
        return tuple(result)

    def _aggregate(self, inputs, _parameters):
        values = [item.value for item in _measures(inputs[0])]
        if any(item is None for item in values):
            raise ExecutionError("Aggregate cannot sum missing measures")
        return (ObjectMeasure(
            "aggregate", sum(values), 1.0  # type: ignore[arg-type]
        ),)

    def _proportion(self, inputs, _parameters):
        result = []
        for item in _measures(inputs[0]):
            if item.value is None:
                result.append(item)
                continue
            if item.denominator <= 0:
                raise ExecutionError(
                    "object {0!r} has a non-positive denominator".format(
                        item.object_name
                    )
                )
            result.append(ObjectMeasure(
                item.object_name, item.value / item.denominator, 1.0
            ))
        return tuple(result)

    def _reclassify(self, inputs, parameters):
        mapping = parameters.get("mapping")
        if not isinstance(mapping, Mapping):
            raise ExecutionError("Reclassify requires a mapping parameter")
        return tuple(FieldRecord(
            item.geometry, mapping.get(item.value, item.value), item.id
        ) for item in _fields(inputs[0]))

    def _buffer(self, inputs, parameters):
        distance = _number(parameters.get("distance", 0), "buffer distance")
        if distance < 0:
            raise ExecutionError("buffer distance cannot be negative")
        return tuple(ObjectRecord(
            item.name,
            (item.geometry[0] - distance, item.geometry[1] - distance,
             item.geometry[2] + distance, item.geometry[3] + distance),
        ) for item in _objects(inputs[0]))

    def _overlay(self, inputs, _parameters):
        left, right = _fields(inputs[0]), _fields(inputs[1])
        result = []
        for a in left:
            for b in right:
                if intersection_area(a.geometry, b.geometry) <= 0:
                    continue
                result.append(FieldRecord(
                    (max(a.geometry[0], b.geometry[0]),
                     max(a.geometry[1], b.geometry[1]),
                     min(a.geometry[2], b.geometry[2]),
                     min(a.geometry[3], b.geometry[3])),
                    "{0}|{1}".format(a.value, b.value),
                    "{0}|{1}".format(a.id, b.id),
                ))
        return tuple(result)


def _parameter_set(parameters: Optional[Mapping[Any, Mapping[str, Any]]],
                   step: Step, index: int,
                   transformation_counts: Mapping[str, int]) -> Mapping[str, Any]:
    if not parameters:
        return {}
    if step.output in parameters:
        return parameters[step.output]
    if index in parameters:
        return parameters[index]
    if (step.transformation in parameters and
            transformation_counts[step.transformation] == 1):
        return parameters[step.transformation]
    return {}


def execute(workflow: Workflow,
            sources: Mapping[str, RuntimeDataset] | Sequence[RuntimeDataset],
            backend: Optional[Backend] = None,
            parameters: Optional[Mapping[Any, Mapping[str, Any]]] = None,
            ) -> ExecutionResult:
    """Execute a type-checked workflow and return its value plus trace.

    ``parameters`` is keyed by generated step names (``step1``, ``step2``),
    by zero-based step index, or by transformation name when that name occurs
    only once. This makes threshold and buffer values explicit rather than
    smuggling them into a transformation name.
    """
    if isinstance(sources, Mapping):
        supplied = dict(sources)
    else:
        supplied = {item.name: item for item in sources}
    expected = {item.name: item for item in workflow.sources}
    missing = sorted(set(expected) - set(supplied))
    if missing:
        raise ExecutionError("missing runtime source(s): " + ", ".join(missing))
    for name, descriptor in expected.items():
        runtime = supplied[name]
        if not isinstance(runtime, RuntimeDataset):
            raise ExecutionError("source {0!r} is not a RuntimeDataset".format(name))
        if not descriptor.type.subsumes(runtime.type):
            raise ExecutionError(
                "source {0!r} declares {1}, runtime value is {2}".format(
                    name, descriptor.type, runtime.type
                )
            )

    active_backend = backend if backend is not None else RectangularBackend()
    values = dict(supplied)
    transformation_counts = {}
    for item in workflow.steps:
        transformation_counts[item.transformation] = (
            transformation_counts.get(item.transformation, 0) + 1
        )
    records = []
    for index, step in enumerate(workflow.steps):
        try:
            inputs = tuple(values[reference] for reference in step.inputs)
        except KeyError as error:
            raise ExecutionError(
                "input {0!r} is not available".format(error.args[0]),
                index, step.transformation,
            ) from error
        params = _parameter_set(parameters, step, index, transformation_counts)
        try:
            payload = active_backend.run(
                step.transformation,
                tuple(item.value for item in inputs),
                params,
            )
        except ExecutionError as error:
            raise ExecutionError(str(error), index, step.transformation) from error
        except Exception as error:
            raise ExecutionError(
                "backend failure: {0}".format(error), index, step.transformation
            ) from error
        runtime = RuntimeDataset(step.output, step.output_type, payload)
        values[step.output] = runtime
        records.append(ExecutionRecord(
            index,
            step.transformation,
            step.inputs,
            step.output,
            tuple(item.type.serialise() for item in inputs),
            step.output_type,
            tuple((str(key), repr(value)) for key, value in sorted(params.items())),
        ))
    if not workflow.steps:
        source = workflow.result
        return ExecutionResult(supplied[source.name], ())
    return ExecutionResult(values[workflow.result.name], tuple(records))


class WorkflowExecutor:
    """Reusable executor facade for applications and experiments."""

    def __init__(self, backend: Optional[Backend] = None):
        self.backend = backend if backend is not None else RectangularBackend()

    def run(self, workflow: Workflow,
            sources: Mapping[str, RuntimeDataset] | Sequence[RuntimeDataset],
            parameters: Optional[Mapping[Any, Mapping[str, Any]]] = None,
            ) -> ExecutionResult:
        return execute(workflow, sources, self.backend, parameters)
