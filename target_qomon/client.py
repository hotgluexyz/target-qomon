"""Qomon target base sink with HTTP, custom-field cache, and payload helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import requests
from hotglue_etl_exceptions import InvalidCredentialsError, InvalidPayloadError
from hotglue_singer_sdk.exceptions import FatalAPIError, RetriableAPIError
from hotglue_singer_sdk.plugin_base import PluginBase
from hotglue_singer_sdk.target_sdk.client import HotglueSink

from target_qomon.contact_lookup import ContactLookupMixin
from target_qomon.custom_fields import (
    custom_field_definitions_by_id,
    custom_field_definitions_by_label,
    custom_field_values_by_label,
    custom_fields_for_sync_write,
)


@dataclass
class _QomonCache:
    custom_fields_by_label: dict[str, dict[str, Any]] = field(default_factory=dict)
    custom_fields_by_id: dict[int, dict[str, Any]] = field(default_factory=dict)
    custom_fields_loaded: bool = False


class QomonSink(ContactLookupMixin, HotglueSink):
    """Base sink for Qomon API interactions."""

    def __init__(
        self,
        target: PluginBase,
        stream_name: str,
        schema: dict,
        key_properties: list[str] | None,
    ) -> None:
        super().__init__(target, stream_name, schema, key_properties)
        self._cache = _QomonCache()

    @property
    def base_url(self) -> str:
        return self.config.get("api_base_url", "https://incoming.qomon.app").rstrip("/") + "/"

    @property
    def endpoint(self) -> str:
        return "contacts"

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config['api_key']}",
        }

    def validate_response(self, response: requests.Response) -> None:
        """Map Qomon HTTP status codes to hotglue exception types."""
        if response.status_code in {401, 403}:
            raise InvalidCredentialsError(response.text or response.reason)
        if response.status_code == 400:
            raise InvalidPayloadError(response.text or response.reason)
        if response.status_code in {429} or 500 <= response.status_code < 600:
            raise RetriableAPIError(self.response_error_message(response), response)
        if 400 <= response.status_code < 500:
            raise FatalAPIError(response.text or response.reason)
        super().validate_response(response)

    @staticmethod
    def _unwrap_data(payload: dict[str, Any], *keys: str) -> Any:
        """Return nested data from a Qomon envelope response."""
        current: Any = payload
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    def _load_forms_by_type(self, form_type: str) -> list[dict[str, Any]]:
        """Fetch all forms for a given type."""
        response = self.request_api("GET", endpoint=f"v1/forms/type/{form_type}")
        payload = response.json()
        forms = self._unwrap_data(payload, "data", "forms")
        if isinstance(forms, list):
            return forms
        return []

    def ensure_custom_fields_loaded(self) -> None:
        """Lazy-load custom field definitions when custom fields are first needed."""
        if self._cache.custom_fields_loaded:
            return
        self.logger.info("Loading custom field definitions into cache")
        definitions = self._load_forms_by_type("custom_fields")
        self._cache.custom_fields_by_label = custom_field_definitions_by_label(definitions)
        self._cache.custom_fields_by_id = custom_field_definitions_by_id(definitions)
        self._cache.custom_fields_loaded = True

    def clean_null_values(self, data: Any) -> Any:
        """Remove null and blank values while preserving non-empty nested structures."""
        if not isinstance(data, dict):
            return data
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            if value is None:
                continue
            if isinstance(value, dict):
                nested = self.clean_null_values(value)
                if nested:
                    cleaned[key] = nested
            elif isinstance(value, list):
                if value:
                    cleaned[key] = value
            elif value != "":
                cleaned[key] = value
        return cleaned

    @staticmethod
    def _merge_custom_fields(
        existing: dict[str, Any],
        incoming: list[Any],
        existing_custom: dict[str, Any],
    ) -> list[dict[str, str]]:
        """Merge custom field entries by label for only_upsert_empty_fields."""
        merged_custom: list[dict[str, str]] = []
        incoming_labels: set[str] = set()
        for entry in incoming:
            if not isinstance(entry, dict):
                continue
            label = entry.get("label") or entry.get("name")
            if label is None:
                continue
            label_str = str(label)
            incoming_labels.add(label_str)
            existing_value = existing_custom.get(label_str)
            if existing_value not in (None, ""):
                merged_custom.append({"label": label_str, "value": str(existing_value)})
                continue
            value = entry.get("value")
            if value is not None:
                merged_custom.append({"label": label_str, "value": str(value)})

        for entry in existing.get("custom_fields") or []:
            if not isinstance(entry, dict):
                continue
            label = entry.get("label") or entry.get("name")
            if label is None:
                continue
            label_str = str(label)
            if label_str in incoming_labels:
                continue
            value = entry.get("value")
            if value in (None, ""):
                continue
            merged_custom.append({"label": label_str, "value": str(value)})
            incoming_labels.add(label_str)

        for formdata in existing.get("formdatas") or []:
            if not isinstance(formdata, dict):
                continue
            label = formdata.get("label") or formdata.get("data")
            if label is None:
                continue
            label_str = str(label)
            if label_str in incoming_labels:
                continue
            value = formdata.get("data")
            if value is None:
                value = formdata.get("value")
            if value in (None, ""):
                continue
            merged_custom.append({"label": label_str, "value": str(value)})

        return merged_custom

    def merge_empty_fields(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep existing non-empty values and fill only empty fields from incoming data."""
        self.ensure_custom_fields_loaded()
        existing_custom = custom_field_values_by_label(existing, self._cache.custom_fields_by_id)
        merged = dict(incoming)
        for key, incoming_value in incoming.items():
            if key == "address" and isinstance(incoming_value, dict):
                existing_address = existing.get("address") or {}
                if not isinstance(existing_address, dict):
                    existing_address = {}
                merged_address = dict(incoming_value)
                for address_key in incoming_value:
                    existing_value = existing_address.get(address_key)
                    if existing_value not in (None, ""):
                        merged_address[address_key] = existing_value
                merged["address"] = merged_address
                continue

            if key == "custom_fields" and isinstance(incoming_value, list):
                merged["custom_fields"] = self._merge_custom_fields(
                    existing,
                    incoming_value,
                    existing_custom,
                )
                continue

            existing_value = existing.get(key)
            if existing_value in (None, "") and key in existing_custom:
                existing_value = existing_custom[key]
            if existing_value not in (None, ""):
                merged[key] = existing_value
        return merged

    _READ_ONLY_CONTACT_KEYS = frozenset(
        {
            "id",
            "CreatedAt",
            "UpdatedAt",
            "lastchange",
            "lastchangeuserid",
            "group_id",
        },
    )

    def _merge_for_sync_update(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """Overlay incoming fields onto an existing contact for PATCH /contacts/{id}."""
        merged = dict(existing)
        for key, value in incoming.items():
            if key == "address" and isinstance(value, dict):
                existing_address = existing.get("address") or {}
                if not isinstance(existing_address, dict):
                    existing_address = {}
                merged["address"] = {**existing_address, **value}
                continue
            merged[key] = value
        return merged

    def _strip_read_only_contact_fields(self, contact: dict[str, Any]) -> dict[str, Any]:
        """Remove read-only top-level contact keys before writing a contact."""
        stripped = {
            key: value
            for key, value in contact.items()
            if key not in self._READ_ONLY_CONTACT_KEYS
        }
        address = stripped.get("address")
        if isinstance(address, dict):
            stripped["address"] = {
                key: value
                for key, value in address.items()
                if key
                not in {
                    "id",
                    "latitude",
                    "longitude",
                    "location",
                    "score",
                }
            }
        return stripped

    def prepare_sync_contact(
        self,
        contact_data: dict[str, Any],
        existing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Merge with an existing contact and adapt payloads for POST/PATCH /contacts."""
        payload = (
            self._merge_for_sync_update(existing, contact_data)
            if existing
            else dict(contact_data)
        )
        custom_fields = payload.get("custom_fields")
        if isinstance(custom_fields, list) and custom_fields:
            self.ensure_custom_fields_loaded()
            converted = custom_fields_for_sync_write(
                custom_fields,
                self._cache.custom_fields_by_label,
                existing,
                self._cache.custom_fields_by_id,
            )
            if not converted:
                raise InvalidPayloadError(
                    "Custom fields could not be mapped for sync contact write.",
                )
            payload["custom_fields"] = converted
        return self._strip_read_only_contact_fields(payload)

    def build_contact_envelope(self, contact_data: dict[str, Any]) -> dict[str, Any]:
        """Wrap contact data in the Qomon synchronous write envelope."""
        return {
            "data": {
                "contact": contact_data,
            },
        }

    def extract_contact_from_response(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Return the contact object from a Qomon write response."""
        contact = self._unwrap_data(payload, "data", "contact")
        if isinstance(contact, dict):
            return contact
        return None
