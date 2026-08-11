"""Qomon target sink classes."""

from __future__ import annotations

from typing import Any

from target_qomon.client import QomonSink
from target_qomon.contact_lookup import contact_for_cache
from target_qomon.unified_mapping import build_contact_payload


class ContactsSink(QomonSink):
    """Unified Contacts sink for Qomon."""

    name = "Contacts"

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._pending_tags: list[str] = []

    @staticmethod
    def _normalize_subscription_status(status: str | None) -> str:
        if not status:
            return "subscribed"
        normalized = str(status).strip().lower()
        if normalized in {"unsubscribed", "unsubscribe", "opt_out", "opt-out"}:
            return "unsubscribed"
        return "subscribed"

    def _apply_subscribe_status(self, payload: dict[str, Any], record: dict[str, Any]) -> None:
        """Map unified subscribe_status to Qomon black_list."""
        status = self._normalize_subscription_status(record.get("subscribe_status"))
        if status == "unsubscribed" and "black_list" not in payload:
            payload["black_list"] = True
        elif status == "subscribed" and record.get("subscribe_status") is not None:
            payload["black_list"] = False

    def _build_tags(self) -> list[dict[str, str]]:
        """Map pending tag names to Qomon tag objects."""
        tags: list[dict[str, str]] = []
        seen: set[str] = set()
        for tag_name in self._pending_tags:
            lowered = tag_name.lower()
            if lowered in seen:
                continue
            tags.append({"name": tag_name})
            seen.add(lowered)
        return tags

    def preprocess_record(self, record: dict[str, Any], context: dict) -> dict:
        """Map, lookup, and merge a unified record before writing to Qomon."""
        self._pending_tags = [
            str(tag).strip()
            for tag in (record.get("tags") or [])
            if tag is not None and str(tag).strip()
        ]

        payload, _custom_field_names = build_contact_payload(record)
        matching_contact = self.find_matching_contact(record)
        only_upsert_empty_fields = bool(self.config.get("only_upsert_empty_fields"))

        if matching_contact:
            if only_upsert_empty_fields:
                payload = self.merge_empty_fields(matching_contact, payload)
            matching_id = matching_contact.get("id")
            if matching_id is not None:
                payload["_qomon_id"] = matching_id

        self._apply_subscribe_status(payload, record)

        tags = self._build_tags()
        if tags:
            payload["tags"] = tags

        return self.clean_null_values(payload)

    def upsert_record(self, record: dict, context: dict):
        """Create or update a contact via the Qomon upsert endpoint."""
        state_dict: dict[str, Any] = {}
        contact_id = record.pop("_qomon_id", None)
        if contact_id is not None:
            record["id"] = contact_id

        envelope = self.build_upsert_envelope(record)
        response = self.request_api(
            "POST",
            endpoint="contacts/upsert",
            request_data=envelope,
        )
        accepted = response.status_code in {200, 202} and response.ok

        cached_contact = None
        if contact_id is not None:
            cached_contact = self._fetch_contact_by_id(str(contact_id))
        self._store_contact_in_cache(contact_for_cache(record, cached_contact))

        state_dict["success"] = accepted
        if contact_id is not None:
            state_dict["is_updated"] = True
        return contact_id, accepted, state_dict
