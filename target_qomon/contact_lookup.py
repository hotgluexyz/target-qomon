"""Contact search lookup for Qomon contact writes."""

from __future__ import annotations

from typing import Any

from hotglue_singer_sdk.exceptions import FatalAPIError

from target_qomon.unified_mapping import (
    SUPPORTED_LOOKUP_FIELDS,
    contact_lookup_value,
    search_attr_for_lookup_field,
    unified_lookup_value,
    values_match,
)

DEFAULT_LOOKUP_FIELDS = ["id", "email"]
SEARCH_RESULT_LIMIT = 50


def _search_operator_for_field(unified_field: str) -> str:
    if unified_field == "email":
        return "eql:strictdata"
    return "eql"


class ContactLookupMixin:
    """Resolve create vs update matches via GET or the Qomon Search API."""

    @property
    def lookup_method(self) -> str:
        method = (self.config.get("lookup_method") or "sequential").lower()
        return method if method in {"sequential", "all"} else "sequential"

    def get_lookup_fields(self) -> list[str]:
        """Return configured lookup fields for this stream, defaulting to id then email."""
        lookup_config = self.config.get("lookup_fields") or {}
        fields = lookup_config.get(self.name) or lookup_config.get("Contacts")
        if fields is None:
            fields = DEFAULT_LOOKUP_FIELDS
        if isinstance(fields, str):
            fields = [fields]
        supported = [field for field in fields if field in SUPPORTED_LOOKUP_FIELDS]
        unsupported = [field for field in fields if field not in SUPPORTED_LOOKUP_FIELDS]
        if unsupported:
            self.logger.warning(
                "Ignoring unsupported lookup fields: %s. Supported: id, email, first_name, last_name, external_id",
                unsupported,
            )
        return supported

    def _record_field_value(self, record: dict[str, Any], field: str) -> Any:
        return unified_lookup_value(record, field)

    def _contact_matches_value(
        self,
        contact: dict[str, Any],
        field: str,
        expected: Any,
    ) -> bool:
        """Return whether a Qomon contact matches a unified lookup field value."""
        actual = contact_lookup_value(contact, field)
        return values_match(field, expected, actual)

    def _build_search_condition(
        self,
        field: str,
        value: Any,
    ) -> dict[str, Any] | None:
        """Build a single Qomon search $condition for a lookup field."""
        if field == "id":
            return None
        attr = search_attr_for_lookup_field(field)
        if not attr:
            return None
        return {
            "$condition": {
                "attr": attr,
                "ope": _search_operator_for_field(field),
                "value": str(value),
            },
        }

    def _lookup_fields_with_values(
        self,
        record: dict[str, Any],
        fields: list[str],
    ) -> list[tuple[str, Any]]:
        populated: list[tuple[str, Any]] = []
        for field in fields:
            value = self._record_field_value(record, field)
            if value in (None, ""):
                continue
            populated.append((field, value))
        return populated

    def _search_contacts(self, inner_group: dict[str, Any]) -> list[dict[str, Any]]:
        """Run a single-page Qomon contact search and return matching contacts."""
        response = self.request_api(
            "POST",
            endpoint="search",
            request_data={
                "data": {
                    "advanced_search": {
                        "per_page": SEARCH_RESULT_LIMIT,
                        "page": 0,
                        "query": {
                            "$all": [inner_group],
                        },
                    },
                },
            },
        )
        payload = response.json()
        contacts = payload.get("data", {}).get("contacts") or []
        if not isinstance(contacts, list):
            return []
        return [contact for contact in contacts if isinstance(contact, dict)]

    def _lookup_by_id(
        self,
        record: dict[str, Any],
        fields: list[str],
    ) -> dict[str, Any] | None:
        if "id" not in fields:
            return None
        contact_id = self._record_field_value(record, "id")
        if contact_id in (None, ""):
            return None
        return self._fetch_contact_by_id(str(contact_id))

    def _lookup_by_search_or(
        self,
        record: dict[str, Any],
        fields: list[str],
    ) -> dict[str, Any] | None:
        """Find a contact matching any populated lookup field (excluding id)."""
        conditions: list[dict[str, Any]] = []
        for field, value in self._lookup_fields_with_values(record, fields):
            if field == "id":
                continue
            condition = self._build_search_condition(field, value)
            if condition:
                conditions.append(condition)
        if not conditions:
            return None

        matches = self._search_contacts({"$at_least_one": conditions})
        if not matches:
            return None
        return matches[0]

    def _lookup_by_search_all(
        self,
        record: dict[str, Any],
        fields: list[str],
    ) -> dict[str, Any] | None:
        """Find a contact matching every configured lookup field."""
        populated = self._lookup_fields_with_values(record, fields)
        if len(populated) != len(fields):
            return None

        id_fields = [(field, value) for field, value in populated if field == "id"]
        if id_fields:
            contact = self._fetch_contact_by_id(str(id_fields[0][1]))
            if contact is None:
                return None
            for field, expected in populated:
                if not self._contact_matches_value(contact, field, expected):
                    return None
            return contact

        conditions: list[dict[str, Any]] = []
        for field, value in populated:
            condition = self._build_search_condition(field, value)
            if condition:
                conditions.append(condition)
        if not conditions:
            return None

        matches = self._search_contacts({"$all": conditions})
        if not matches:
            return None
        return matches[0]

    def find_matching_contact(self, record: dict[str, Any]) -> dict[str, Any] | None:
        """Resolve an existing contact using GET (for id) or the Search API."""
        fields = self.get_lookup_fields()
        if not fields:
            return None

        if self.lookup_method == "all":
            match = self._lookup_by_search_all(record, fields)
        else:
            match = self._lookup_by_id(record, fields)
            if match is None:
                match = self._lookup_by_search_or(record, fields)

        if match:
            self.logger.info("Found existing contact id %s", match.get("id"))
        return match

    def _fetch_contact_by_id(self, contact_id: str) -> dict[str, Any] | None:
        """Fetch a contact by id."""
        try:
            response = self.request_api("GET", endpoint=f"contacts/{contact_id}")
        except FatalAPIError:
            return None
        payload = response.json()
        contact = payload.get("data", {}).get("contact") or payload.get("contact") or payload
        if isinstance(contact, dict):
            return contact
        return None
