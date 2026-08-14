"""Qomon target class."""

from typing import ClassVar

from hotglue_singer_sdk import typing as th
from hotglue_singer_sdk.helpers.capabilities import AlertingLevel
from hotglue_singer_sdk.target_sdk.target import TargetHotglue

from target_qomon.sinks import ContactsSink


class TargetQomon(TargetHotglue):
    """Target for Qomon unified Contacts."""

    SINK_TYPES: ClassVar = [
        ContactsSink,
    ]
    name = "target-qomon"
    alerting_level = AlertingLevel.ERROR

    config_jsonschema = th.PropertiesList(
        th.Property(
            "api_key",
            th.StringType,
            required=True,
            description="Qomon API key from space settings.",
        ),
        th.Property(
            "api_base_url",
            th.StringType,
            description="Qomon API base URL, e.g. If not provided, the default will be used. https://incoming.qomon.app",
        ),
        th.Property(
            "only_upsert_empty_fields",
            th.BooleanType,
            description="Only update Qomon fields that are currently empty.",
        ),
        th.Property(
            "lookup_method",
            th.StringType,
            description='Lookup strategy: "sequential" or "all". Defaults to sequential.',
        ),
        th.Property(
            "lookup_fields",
            th.ObjectType(),
            description='Per-stream lookup fields, e.g. {"Contacts": ["id", "email"]}.',
        ),
    ).to_dict()


if __name__ == "__main__":
    TargetQomon.cli()
