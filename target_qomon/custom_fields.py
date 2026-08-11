"""Custom field helpers for target-qomon."""

from __future__ import annotations

from typing import Any


def custom_field_definitions_by_label(
    definitions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index custom field form definitions by label, keeping the first occurrence."""
    by_label: dict[str, dict[str, Any]] = {}
    for definition in definitions:
        label = definition.get("label") or definition.get("name")
        if label and label not in by_label:
            by_label[label] = definition
            by_label[str(label).lower()] = definition
    return by_label


def custom_field_values_by_label(contact: dict[str, Any]) -> dict[str, Any]:
    """Return custom field values from a Qomon contact payload keyed by label."""
    by_label: dict[str, Any] = {}
    for entry in contact.get("custom_fields") or []:
        if not isinstance(entry, dict):
            continue
        label = entry.get("label") or entry.get("name")
        if label is None:
            continue
        value = entry.get("value")
        if value is not None:
            by_label[str(label)] = value
    for formdata in contact.get("formdatas") or []:
        if not isinstance(formdata, dict):
            continue
        label = formdata.get("label") or formdata.get("data")
        if label is None:
            continue
        value = formdata.get("data") or formdata.get("value")
        if value is not None:
            by_label[str(label)] = value
    return by_label
