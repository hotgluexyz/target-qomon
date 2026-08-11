"""Unified CRM field names mapped to Qomon contact API fields."""

from __future__ import annotations

from typing import Any

# Unified field name -> Qomon contact payload key.
UNIFIED_TO_QOMON: dict[str, str] = {
    "first_name": "firstname",
    "last_name": "surname",
    "email": "mail",
    "externalId": "external_id",
    "external_id": "external_id",
}

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
    "mail": "mail",
    "external_id": "external_id",
    "externalId": "external_id",
    "first_name": "firstname",
    "firstname": "firstname",
    "last_name": "surname",
    "surname": "surname",
    "mobile": "mobile",
    "phone": "phone",
    "city": "address.city",
    "postal_code": "address.postalcode",
    "postalcode": "address.postalcode",
    "country": "address.country",
    "street": "address.street",
    "address": "address.street",
    "line1": "address.street",
}

NON_DIALABLE_PHONE_TYPES = {"fax", "pager"}


def qomon_field_name(unified_field: str) -> str:
    """Return the Qomon contact key used for a unified field."""
    if unified_field in ADDRESS_FIELD_TO_QOMON:
        return ADDRESS_FIELD_TO_QOMON[unified_field]
    return UNIFIED_TO_QOMON.get(unified_field, unified_field)


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
    if unified_field in {"email", "mail"} and record.get("email"):
        return str(record["email"]).strip().lower()
    if unified_field in {"external_id", "externalId"}:
        return record.get("external_id") or record.get("externalId")
    if unified_field == "phone":
        return extract_phones(record)[0]
    if unified_field == "mobile":
        return extract_phones(record)[1]

    address = _first_address(record)
    for address_key, qomon_key in ADDRESS_FIELD_TO_QOMON.items():
        if unified_field == qomon_key or unified_field == address_key:
            return address.get(address_key) or record.get(unified_field)

    qomon_key = qomon_field_name(unified_field)
    return record.get(unified_field) or record.get(qomon_key)


def contact_lookup_value(contact: dict[str, Any], unified_field: str) -> Any:
    """Read a comparable lookup value from a cached Qomon contact."""
    if unified_field == "id":
        return contact.get("id")
    if unified_field in {"email", "mail"} and contact.get("mail"):
        return str(contact["mail"]).strip().lower()
    if unified_field in {"external_id", "externalId"}:
        return contact.get("external_id")
    if unified_field in {"phone", "mobile"}:
        return contact.get(unified_field)

    qomon_key = qomon_field_name(unified_field)
    if qomon_key == "street":
        address = contact.get("address") or {}
        if isinstance(address, dict):
            return address.get("street") or contact.get("street")
    if qomon_key in {"city", "postalcode", "country", "state"}:
        address = contact.get("address") or {}
        if isinstance(address, dict):
            return address.get(qomon_key)
    return contact.get(qomon_key)


def values_match(unified_field: str, expected: Any, actual: Any) -> bool:
    """Compare lookup values from a unified record and a Qomon contact."""
    if actual in (None, ""):
        return False
    if expected in (None, ""):
        return False
    if unified_field in {"email", "mail"}:
        return str(actual).strip().lower() == str(expected).strip().lower()
    return str(actual) == str(expected)


def search_attr_for_lookup_field(unified_field: str) -> str | None:
    """Return the Qomon search attribute for a unified lookup field."""
    return LOOKUP_FIELD_TO_SEARCH_ATTR.get(unified_field) or LOOKUP_FIELD_TO_SEARCH_ATTR.get(
        qomon_field_name(unified_field),
    )
