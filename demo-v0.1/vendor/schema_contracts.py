from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SchemaIssue:
    instance_path: str
    schema_path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "instance_path": self.instance_path,
            "schema_path": self.schema_path,
            "message": self.message,
        }


class SchemaContractError(ValueError):
    """Raised when a bundled schema is unsafe or internally invalid."""


class SchemaStore:
    """Dependency-free validator for the JSON Schema subset used by SceneGuard.

    It deliberately rejects remote and escaping references. The published schemas stay
    standard Draft 2020-12 documents, so downstream users may replace this validator
    with any conforming JSON Schema implementation.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self._cache: dict[Path, dict[str, Any]] = {}

    def load(self, path: str | Path) -> tuple[Path, dict[str, Any]]:
        candidate = (self.root / path).resolve() if not Path(path).is_absolute() else Path(path).resolve()
        if not candidate.is_relative_to(self.root):
            raise SchemaContractError(f"schema path escapes root: {path}")
        if candidate.suffix.lower() != ".json":
            raise SchemaContractError(f"schema must be JSON: {path}")
        if candidate not in self._cache:
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise SchemaContractError(f"cannot load schema {path}: {exc}") from exc
            if not isinstance(payload, dict):
                raise SchemaContractError(f"schema root must be an object: {path}")
            if payload.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
                raise SchemaContractError(f"schema must declare Draft 2020-12: {path}")
            self._cache[candidate] = payload
        return candidate, self._cache[candidate]

    def validate(self, instance: Any, schema_path: str | Path) -> list[SchemaIssue]:
        source, schema = self.load(schema_path)
        return self._validate(instance, schema, source, "$", "#")

    def _validate(
        self,
        instance: Any,
        schema: Any,
        source: Path,
        instance_path: str,
        schema_path: str,
    ) -> list[SchemaIssue]:
        if isinstance(schema, bool):
            return [] if schema else [SchemaIssue(instance_path, schema_path, "boolean schema rejected value")]
        if not isinstance(schema, dict):
            raise SchemaContractError(f"schema node is not an object at {source}:{schema_path}")

        if "$ref" in schema:
            target_source, target_schema, target_path = self._resolve_ref(source, schema["$ref"])
            return self._validate(instance, target_schema, target_source, instance_path, target_path)

        issues: list[SchemaIssue] = []
        for keyword in ("allOf",):
            if keyword in schema:
                for index, branch in enumerate(_schema_array(schema[keyword], source, schema_path, keyword)):
                    issues.extend(
                        self._validate(instance, branch, source, instance_path, f"{schema_path}/{keyword}/{index}")
                    )
        for keyword in ("anyOf", "oneOf"):
            if keyword in schema:
                branches = _schema_array(schema[keyword], source, schema_path, keyword)
                branch_results = [
                    self._validate(instance, branch, source, instance_path, f"{schema_path}/{keyword}/{index}")
                    for index, branch in enumerate(branches)
                ]
                passing = sum(not result for result in branch_results)
                expected = "at least one" if keyword == "anyOf" else "exactly one"
                if (keyword == "anyOf" and passing == 0) or (keyword == "oneOf" and passing != 1):
                    issues.append(SchemaIssue(instance_path, f"{schema_path}/{keyword}", f"must match {expected} branch"))

        if "const" in schema and instance != schema["const"]:
            issues.append(SchemaIssue(instance_path, f"{schema_path}/const", f"must equal {schema['const']!r}"))
        if "enum" in schema:
            enum = schema["enum"]
            if not isinstance(enum, list) or not enum:
                raise SchemaContractError(f"enum must be a non-empty array at {source}:{schema_path}")
            if instance not in enum:
                issues.append(SchemaIssue(instance_path, f"{schema_path}/enum", "value is not in the allowed enum"))

        expected_types = schema.get("type")
        if expected_types is not None:
            names = [expected_types] if isinstance(expected_types, str) else expected_types
            if not isinstance(names, list) or not names or any(not isinstance(name, str) for name in names):
                raise SchemaContractError(f"type must be a string or non-empty string array at {source}:{schema_path}")
            if not any(_is_type(instance, name) for name in names):
                issues.append(
                    SchemaIssue(instance_path, f"{schema_path}/type", "expected type " + " or ".join(names))
                )
                return issues

        if isinstance(instance, dict):
            required = schema.get("required", [])
            if not isinstance(required, list) or any(not isinstance(name, str) for name in required):
                raise SchemaContractError(f"required must be a string array at {source}:{schema_path}")
            for name in required:
                if name not in instance:
                    issues.append(
                        SchemaIssue(instance_path, f"{schema_path}/required", f"missing required property {name!r}")
                    )
            properties = schema.get("properties", {})
            if not isinstance(properties, dict):
                raise SchemaContractError(f"properties must be an object at {source}:{schema_path}")
            for name, value in instance.items():
                child_path = f"{instance_path}/{_pointer(name)}"
                if name in properties:
                    issues.extend(
                        self._validate(value, properties[name], source, child_path, f"{schema_path}/properties/{_pointer(name)}")
                    )
                elif schema.get("additionalProperties") is False:
                    issues.append(
                        SchemaIssue(child_path, f"{schema_path}/additionalProperties", "additional property is not allowed")
                    )
                elif isinstance(schema.get("additionalProperties"), dict):
                    issues.extend(
                        self._validate(
                            value,
                            schema["additionalProperties"],
                            source,
                            child_path,
                            f"{schema_path}/additionalProperties",
                        )
                    )

        if isinstance(instance, list):
            minimum = schema.get("minItems")
            if isinstance(minimum, int) and len(instance) < minimum:
                issues.append(SchemaIssue(instance_path, f"{schema_path}/minItems", f"requires at least {minimum} items"))
            if schema.get("uniqueItems") is True:
                serialized = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in instance]
                if len(serialized) != len(set(serialized)):
                    issues.append(SchemaIssue(instance_path, f"{schema_path}/uniqueItems", "items must be unique"))
            if "items" in schema:
                for index, value in enumerate(instance):
                    issues.extend(
                        self._validate(value, schema["items"], source, f"{instance_path}/{index}", f"{schema_path}/items")
                    )

        if isinstance(instance, str):
            minimum = schema.get("minLength")
            maximum = schema.get("maxLength")
            if isinstance(minimum, int) and len(instance) < minimum:
                issues.append(SchemaIssue(instance_path, f"{schema_path}/minLength", f"requires length >= {minimum}"))
            if isinstance(maximum, int) and len(instance) > maximum:
                issues.append(SchemaIssue(instance_path, f"{schema_path}/maxLength", f"requires length <= {maximum}"))
            pattern = schema.get("pattern")
            if pattern is not None:
                if not isinstance(pattern, str):
                    raise SchemaContractError(f"pattern must be a string at {source}:{schema_path}")
                if re.search(pattern, instance) is None:
                    issues.append(SchemaIssue(instance_path, f"{schema_path}/pattern", "string does not match pattern"))
            if schema.get("format") == "date-time":
                try:
                    datetime.fromisoformat(instance.replace("Z", "+00:00"))
                except ValueError:
                    issues.append(SchemaIssue(instance_path, f"{schema_path}/format", "invalid ISO 8601 date-time"))

        if _is_number(instance):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if isinstance(minimum, (int, float)) and instance < minimum:
                issues.append(SchemaIssue(instance_path, f"{schema_path}/minimum", f"must be >= {minimum}"))
            if isinstance(maximum, (int, float)) and instance > maximum:
                issues.append(SchemaIssue(instance_path, f"{schema_path}/maximum", f"must be <= {maximum}"))
        return issues

    def _resolve_ref(self, source: Path, reference: Any) -> tuple[Path, Any, str]:
        if not isinstance(reference, str) or not reference:
            raise SchemaContractError(f"invalid $ref in {source}")
        file_part, separator, fragment = reference.partition("#")
        if "://" in file_part:
            raise SchemaContractError(f"remote $ref is not allowed: {reference}")
        target = source if not file_part else (source.parent / file_part).resolve()
        if not target.is_relative_to(self.root):
            raise SchemaContractError(f"$ref escapes schema root: {reference}")
        _, document = self.load(target)
        node: Any = document
        pointer = "#"
        if separator and fragment:
            if not fragment.startswith("/"):
                raise SchemaContractError(f"only JSON Pointer fragments are supported: {reference}")
            for raw in fragment[1:].split("/"):
                token = raw.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or token not in node:
                    raise SchemaContractError(f"unresolved $ref: {reference}")
                node = node[token]
                pointer += "/" + _pointer(token)
        return target, node, pointer


def _schema_array(value: Any, source: Path, schema_path: str, keyword: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise SchemaContractError(f"{keyword} must be a non-empty array at {source}:{schema_path}")
    return value


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_type(value: Any, name: str) -> bool:
    return {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": _is_number(value),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(name, False)
