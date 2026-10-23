"""Qomon target sink classes."""

from __future__ import annotations

from typing import Any

from target_qomon.client import QomonSink
from target_qomon.unified_mapping import build_contact_payload

# Consent refvalue prefixes, e.g. consent_email / double_optin_sms / no_consent_email.
CONSENT_OPT_IN_PREFIXES = ("consent_", "double_optin_")
CONSENT_OPT_OUT_PREFIX = "no_consent_"


class ContactsSink(QomonSink):
    """Unified Contacts sink for Qomon."""

    name = "Contacts"

    @staticmethod
    def _normalize_subscription_status(status: str | None) -> str:
        if not status:
            return "subscribed"
        normalized = str(status).strip().lower()
        if normalized in {"unsubscribed", "unsubscribe", "opt_out", "opt-out"}:
            return "unsubscribed"
        return "subscribed"

    def _apply_consent_opt_outs(
        self,
        payload: dict[str, Any],
        existing: dict[str, Any] | None,
    ) -> bool:
        """Opt out of every consent channel; return False when the space has none."""
        self.ensure_consent_forms_loaded()
        opt_in_refs: set[tuple[Any, Any]] = set()
        opt_outs: list[dict[str, Any]] = []
        for form in self._cache.consent_forms:
            for refvalue in form.get("refvalues") or []:
                value = str(refvalue.get("value") or "")
                ref = (form.get("id"), refvalue.get("id"))
                if value.startswith(CONSENT_OPT_OUT_PREFIX):
                    opt_outs.append({"form_id": ref[0], "form_ref_id": ref[1], "data": value})
                elif value.startswith(CONSENT_OPT_IN_PREFIXES):
                    opt_in_refs.add(ref)
        if not opt_outs:
            return False

        # PATCH replaces formdatas, so keep other answers and drop channel opt-ins.
        replaced_refs = opt_in_refs | {(e["form_id"], e["form_ref_id"]) for e in opt_outs}
        kept = [
            formdata
            for formdata in (existing or {}).get("formdatas") or []
            if isinstance(formdata, dict)
            and (formdata.get("form_id"), formdata.get("form_ref_id")) not in replaced_refs
        ]
        payload["formdatas"] = kept + opt_outs
        return True

    def _apply_subscribe_status(
        self,
        payload: dict[str, Any],
        record: dict[str, Any],
        existing: dict[str, Any] | None = None,
    ) -> None:
        """Map unified subscribe_status to Qomon consents, falling back to black_list."""
        status = self._normalize_subscription_status(record.get("subscribe_status"))
        if status == "unsubscribed" and "black_list" not in payload:
            if not self._apply_consent_opt_outs(payload, existing):
                payload["black_list"] = True
        elif status == "subscribed" and record.get("subscribe_status") is not None:
            payload["black_list"] = False

    @staticmethod
    def _build_tags(tags: list[Any]) -> list[dict[str, str]]:
        """Map unified tag strings to Qomon tag objects."""
        return [
            {"name": str(tag).strip()}
            for tag in tags
            if tag is not None and str(tag).strip()
        ]

    def preprocess_record(self, record: dict[str, Any], context: dict) -> dict:
        """Map, lookup, and merge a unified record before writing to Qomon."""
        payload, _custom_field_names = build_contact_payload(record)
        matching_contact = self.find_matching_contact(record)
        only_upsert_empty_fields = bool(self.config.get("only_upsert_empty_fields"))

        if matching_contact and only_upsert_empty_fields:
            payload = self.merge_empty_fields(matching_contact, payload)

        self._apply_subscribe_status(payload, record, matching_contact)

        if record.get("tags"):
            payload["tags"] = self._build_tags(record["tags"])

        payload = self.clean_null_values(payload)
        payload = self.prepare_sync_contact(payload, matching_contact)

        matching_id = matching_contact.get("id") if matching_contact else None
        if matching_id is not None:
            payload["_qomon_id"] = matching_id

        return payload

    def upsert_record(self, record: dict, context: dict):
        """Create or update a contact via synchronous Qomon write endpoints."""
        state_dict: dict[str, Any] = {}
        contact_id = record.pop("_qomon_id", None)
        is_update = contact_id is not None
        envelope = self.build_contact_envelope(record)

        if is_update:
            response = self.request_api(
                "PATCH",
                endpoint=f"contacts/{contact_id}",
                request_data=envelope,
            )
            accepted = response.status_code == 200 and response.ok
        else:
            response = self.request_api(
                "POST",
                endpoint="contacts",
                request_data=envelope,
            )
            accepted = response.status_code == 200 and response.ok
            created_contact = self.extract_contact_from_response(response.json())
            if created_contact and created_contact.get("id") is not None:
                contact_id = created_contact["id"]

        state_dict["success"] = accepted
        if is_update:
            state_dict["is_updated"] = True
        return contact_id, accepted, state_dict
