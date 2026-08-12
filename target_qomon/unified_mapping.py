"""Unified CRM field names mapped to Qomon contact API fields."""

from __future__ import annotations

from typing import Any

# Standard Qomon contact payload keys (not custom field definitions).
QOMON_NATIVE_CONTACT_FIELDS = frozenset(
    {
        "id",
        "firstname",
        "surname",
        "married_name",
        "gender",
        "birthdate",
        "birthcity",
        "birthcountry",
        "birthdept",
        "mail",
        "phone",
        "mobile",
        "external_id",
        "nationbuilderid",
        "black_list",
        "nationality",
        "notes",
        "tags",
        "consents",
        "custom_fields",
        "status",
        "forms",
        "actions",
        "name_presences",
        "address",
    },
)

# Address sub-fields: unified address dict key -> Qomon address key.
ADDRESS_FIELD_TO_QOMON: dict[str, str] = {
    "line1": "street",
    "city": "city",
    "state": "state",
    "postal_code": "postalcode",
    "postalCode": "postalcode",
    "country": "country",
    "housenumber": "housenumber",
}

# Unified lookup field -> Qomon search attribute.
LOOKUP_FIELD_TO_SEARCH_ATTR: dict[str, str] = {
    "id": "id",
    "email": "mail",
    "first_name": "firstname",
    "last_name": "surname",
    "external_id": "external_id",
}

SUPPORTED_LOOKUP_FIELDS = frozenset(LOOKUP_FIELD_TO_SEARCH_ATTR)

NON_DIALABLE_PHONE_TYPES = {"fax", "pager"}


def extract_phones(record: dict[str, Any]) -> tuple[str | None, str | None]:
    """Map unified phone_numbers to Qomon phone and mobile values."""
    phone = None
    mobile = None
    for entry in record.get("phone_numbers") or []:
        if not isinstance(entry, dict):
            continue
        number = entry.get("number")
        if not number:
            continue
        phone_type = str(entry.get("type") or "").lower()
        if phone_type in NON_DIALABLE_PHONE_TYPES:
            continue
        if phone_type in {"primary", "home", "work", "phone"} and not phone:
            phone = str(number)
        elif phone_type == "mobile" and not mobile:
            mobile = str(number)
        elif not phone:
            phone = str(number)
    if not mobile and phone:
        mobile = phone
    if not phone and mobile:
        phone = mobile
    return phone, mobile


def _first_address(record: dict[str, Any]) -> dict[str, Any]:
    addresses = record.get("addresses") or []
    if addresses and isinstance(addresses[0], dict):
        return addresses[0]
    return {}


def build_address(record: dict[str, Any]) -> dict[str, Any] | None:
    """Map the first unified address to a Qomon address object."""
    address = _first_address(record)
    if not address:
        return None
    payload: dict[str, Any] = {}
    for unified_key, qomon_key in ADDRESS_FIELD_TO_QOMON.items():
        value = address.get(unified_key)
        if value not in (None, ""):
            payload[qomon_key] = value
    return payload or None


def build_contact_payload(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Map a unified contact record to a Qomon contact write payload."""
    phone, mobile = extract_phones(record)
    payload: dict[str, Any] = {
        "firstname": record.get("first_name"),
        "surname": record.get("last_name"),
        "mail": record.get("email"),
        "phone": phone,
        "mobile": mobile,
        "external_id": record.get("external_id") or record.get("externalId"),
    }

    address = build_address(record)
    if address:
        payload["address"] = address

    custom_field_names: list[str] = []
    custom_fields: list[dict[str, str]] = []
    for custom_field in record.get("custom_fields") or []:
        if not isinstance(custom_field, dict):
            continue
        field_name = custom_field.get("name")
        if not field_name:
            continue
        value = custom_field.get("value")
        if value is None:
            continue
        custom_fields.append({"label": str(field_name), "value": str(value)})
        if field_name not in QOMON_NATIVE_CONTACT_FIELDS:
            custom_field_names.append(str(field_name))
    if custom_fields:
        payload["custom_fields"] = custom_fields

    return payload, custom_field_names


def unified_lookup_value(record: dict[str, Any], unified_field: str) -> Any:
    """Read a lookup value from a unified contact record."""
    if unified_field == "id":
        return record.get("id")
    if unified_field == "email" and record.get("email"):
        return str(record["email"]).strip().lower()
    if unified_field == "external_id":
        return record.get("external_id") or record.get("externalId")
    if unified_field == "first_name":
        return record.get("first_name")
    if unified_field == "last_name":
        return record.get("last_name")
    return None


def contact_lookup_value(contact: dict[str, Any], unified_field: str) -> Any:
    """Read a comparable lookup value from a Qomon contact."""
    qomon_field = LOOKUP_FIELD_TO_SEARCH_ATTR.get(unified_field)
    if qomon_field is None:
        return None
    if unified_field == "email" and contact.get("mail"):
        return str(contact["mail"]).strip().lower()
    return contact.get(qomon_field)


def values_match(unified_field: str, expected: Any, actual: Any) -> bool:
    """Compare lookup values from a unified record and a Qomon contact."""
    if actual in (None, ""):
        return False
    if expected in (None, ""):
        return False
    if unified_field == "email":
        return str(actual).strip().lower() == str(expected).strip().lower()
    return str(actual) == str(expected)


def search_attr_for_lookup_field(unified_field: str) -> str | None:
    """Return the Qomon search attribute for a unified lookup field."""
    return LOOKUP_FIELD_TO_SEARCH_ATTR.get(unified_field)
