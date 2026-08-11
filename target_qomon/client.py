"""Qomon target base sink with HTTP, entity caches, and payload helpers."""

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
    custom_field_definitions_by_label,
    custom_field_values_by_label,
)


@dataclass
class _QomonCache:
    contacts_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    contacts_by_email: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    contacts_loaded: bool = False
    custom_fields_by_label: dict[str, dict[str, Any]] = field(default_factory=dict)
    custom_fields_loaded: bool = False


class QomonSink(ContactLookupMixin, HotglueSink):
    """Base sink for Qomon API interactions."""

    page_size = 1000

    def __init__(
        self,
        target: PluginBase,
        stream_name: str,
        schema: dict,
        key_properties: list[str] | None,
    ) -> None:
        super().__init__(target, stream_name, schema, key_properties)
        self._cache = _QomonCache()
        self._duplicate_emails_logged: set[str] = set()

    @property
    def base_url(self) -> str:
        return self.config["api_base_url"].rstrip("/") + "/"

    @property
    def endpoint(self) -> str:
        return "contacts/upsert"

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

    def _paginate_contacts(self) -> list[dict[str, Any]]:
        """Fetch contacts from the Qomon search API."""
        results: list[dict[str, Any]] = []
        page = 0
        while True:
            response = self.request_api(
                "POST",
                endpoint="search",
                request_data={
                    "data": {
                        "advanced_search": {
                            "per_page": self.page_size,
                            "page": page,
                            "query": {
                                "$all": [
                                    {
                                        "$all": [
                                            {
                                                "$condition": {
                                                    "attr": "mail",
                                                    "ope": "ext",
                                                },
                                            },
                                        ],
                                    },
                                ],
                            },
                        },
                    },
                },
            )
            payload = response.json()
            contacts = payload.get("data", {}).get("contacts") or []
            if not isinstance(contacts, list):
                break
            results.extend(contacts)
            if len(contacts) < self.page_size:
                break
            page += 1
        return results

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

    def merge_empty_fields(
        self,
        existing: dict[str, Any],
        incoming: dict[str, Any],
    ) -> dict[str, Any]:
        """Keep existing non-empty values and fill only empty fields from incoming data."""
        self.ensure_custom_fields_loaded()
        existing_custom = custom_field_values_by_label(existing)
        merged = dict(incoming)
        for key, incoming_value in incoming.items():
            if key == "address" and isinstance(incoming_value, dict):
                existing_address = existing.get("address") or {}
                if not isinstance(existing_address, dict):
                    existing_address = {}
                merged_address = dict(incoming_value)
                for address_key, address_value in incoming_value.items():
                    existing_value = existing_address.get(address_key)
                    if existing_value not in (None, ""):
                        merged_address[address_key] = existing_value
                merged["address"] = merged_address
                continue

            existing_value = existing.get(key)
            if existing_value in (None, "") and key in existing_custom:
                existing_value = existing_custom[key]
            if existing_value not in (None, ""):
                merged[key] = existing_value
        return merged

    def build_upsert_envelope(self, contact_data: dict[str, Any]) -> dict[str, Any]:
        """Wrap contact data in the Qomon upsert envelope."""
        return {
            "kind": "contact",
            "data": contact_data,
        }
