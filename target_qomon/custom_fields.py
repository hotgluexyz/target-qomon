"""Custom field helpers for target-qomon."""

from __future__ import annotations

from typing import Any

TEXT_LIKE_FORM_TYPES = frozenset({"text", "numeric", "date"})


def custom_field_definitions_by_label(
    definitions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Index custom field form definitions by label, keeping the first occurrence."""
    by_label: dict[str, dict[str, Any]] = {}
    for definition in definitions:
        label = definition.get("label") or definition.get("name")
        if label and label not in by_label:
            by_label[label] = definition
    return by_label


def custom_field_definitions_by_id(
    definitions: list[dict[str, Any]],
) -> dict[int, dict[str, Any]]:
    """Index custom field form definitions by form id."""
    by_id: dict[int, dict[str, Any]] = {}
    for definition in definitions:
        form_id = definition.get("id")
        if form_id is not None:
            by_id[int(form_id)] = definition
    return by_id

def _label_for_entry(
    entry: dict[str, Any],
    definitions_by_id: dict[int, dict[str, Any]],
) -> str | None:
    label = entry.get("label") or entry.get("name")
    if label is not None:
        return str(label)
    form_id = entry.get("form_id")
    if form_id is None:
        return None
    definition = definitions_by_id.get(int(form_id))
    if not definition:
        return None
    definition_label = definition.get("label") or definition.get("name")
    return str(definition_label) if definition_label is not None else None


def _resolve_refvalue(definition: dict[str, Any], value: str) -> dict[str, Any] | None:
    refvalues = definition.get("refvalues") or []
    if not refvalues:
        return None
    form_type = str(definition.get("type") or "").lower()
    if form_type in TEXT_LIKE_FORM_TYPES:
        return refvalues[0]
    normalized = value.strip().lower()
    for refvalue in refvalues:
        if not isinstance(refvalue, dict):
            continue
        if str(refvalue.get("value", "")).strip().lower() == normalized:
            return refvalue
        if str(refvalue.get("label", "")).strip().lower() == normalized:
            return refvalue
    return None


def custom_field_for_sync_write(
    label: str,
    value: Any,
    definitions_by_label: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Map a label/value pair to a sync create/update custom_fields entry."""
    definition = definitions_by_label.get(label)
    if not definition:
        return None
    form_id = definition.get("id")
    if form_id is None:
        return None
    refvalue = _resolve_refvalue(definition, str(value))
    if not refvalue:
        return None
    form_ref_id = refvalue.get("id")
    if form_ref_id is None:
        return None
    form_type = str(definition.get("type") or "").lower()
    entry: dict[str, Any] = {
        "form_id": form_id,
        "form_ref_id": form_ref_id,
    }
    if form_type in TEXT_LIKE_FORM_TYPES:
        entry["data"] = str(value)
    else:
        entry["data"] = refvalue.get("value") or str(value)
    return entry


def custom_field_values_by_label(
    contact: dict[str, Any],
    definitions_by_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return custom field values from a Qomon contact payload keyed by label."""
    by_label: dict[str, Any] = {}
    for entry in contact.get("custom_fields") or []:
        if not isinstance(entry, dict):
            continue
        label = _label_for_entry(entry, definitions_by_id or {})
        if label is None:
            continue
        value = entry.get("value")
        if value is None:
            value = entry.get("data")
        if value is not None:
            by_label[label] = value
    for formdata in contact.get("formdatas") or []:
        if not isinstance(formdata, dict):
            continue
        label = _label_for_entry(formdata, definitions_by_id or {})
        if label is None:
            label = formdata.get("label") or formdata.get("data")
        if label is None:
            continue
        value = formdata.get("data") or formdata.get("value")
        if value is not None:
            by_label[str(label)] = value
    return by_label


def custom_fields_for_sync_write(
    entries: list[Any],
    definitions_by_label: dict[str, dict[str, Any]],
    existing_contact: dict[str, Any] | None = None,
    definitions_by_id: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Convert label/value custom field entries for POST/PATCH /contacts."""
    values_by_label: dict[str, Any] = {}
    if existing_contact:
        values_by_label.update(
            custom_field_values_by_label(existing_contact, definitions_by_id),
        )

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if entry.get("form_id") is not None and entry.get("form_ref_id") is not None:
            label = _label_for_entry(entry, definitions_by_id or {})
            data = entry.get("data") or entry.get("value")
            if label is not None and data is not None:
                values_by_label[label] = data
            continue
        label = entry.get("label") or entry.get("name")
        if label is None:
            continue
        value = entry.get("value")
        if value is None:
            continue
        values_by_label[str(label)] = value

    converted: list[dict[str, Any]] = []
    for label, value in values_by_label.items():
        sync_entry = custom_field_for_sync_write(label, value, definitions_by_label)
        if sync_entry:
            converted.append(sync_entry)
    return converted
