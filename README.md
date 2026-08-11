# target-qomon

`target-qomon` is a Singer target for [Qomon](https://qomon.app), built with the [Hotglue Singer SDK](https://github.com/hotgluexyz/HotglueSingerSDK) for Singer Targets.

## Installation

```bash
pip install target-qomon
```

Or from source:

```bash
pip install -e .
```

## Configuration

| Field | Required | Description |
| --- | --- | --- |
| `api_key` | Yes | Qomon API key from account settings |
| `api_base_url` | Yes | Qomon API base URL, e.g. `https://incoming.qomon.app` |
| `only_upsert_empty_fields` | No | Only update Qomon fields that are currently empty |
| `lookup_fields` | No | Per-stream lookup fields, e.g. `{"Contacts": ["id", "email"]}` |
| `lookup_method` | No | `sequential` (default) or `all` |

Example `config.json`:

```json
{
  "api_key": "YOUR_API_KEY",
  "api_base_url": "https://incoming.qomon.app",
  "lookup_fields": {
    "Contacts": ["id", "email"]
  },
  "lookup_method": "sequential",
  "only_upsert_empty_fields": false
}
```

### Lookup fields

Qomon has no server-side match API for all lookup scenarios, so upserts resolve existing contacts from a contact cache loaded once per job. Configure `lookup_fields` and `lookup_method` (`sequential` or `all`) to control how records are matched before create vs update.

Supported examples:

| Unified field | Qomon field |
| --- | --- |
| `id` | `id` |
| `email` | `mail` |
| `external_id`, `externalId` | `external_id` |
| `first_name` | `firstname` |
| `last_name` | `surname` |
| `mobile`, `phone` | `mobile`, `phone` |
| `city`, `postal_code`, `country`, `address` | address sub-fields |

## Source Authentication and Authorization

Qomon uses a static API key. Create one in the Qomon UI under account settings and use it with the `Authorization: Bearer <api_key>` header.

See the [Qomon developer docs](https://developers.qomon.com/pages/v1/getting-started.md) for details.

## Supported Streams

| Stream | Description |
| --- | --- |
| `Contacts` | Unified contacts sink with tags, custom fields, and upsert support |

## Usage

```bash
cat sample_payload/data.singer | target-qomon --config .secrets/config.json
```

## Developer Resources

Create `.secrets/config.json` with your sandbox credentials:

```json
{
  "api_key": "YOUR_API_KEY",
  "api_base_url": "https://incoming.qomon.app"
}
```

Run lint:

```bash
python -m venv .venv
.venv/bin/pip install -e . ruff tox
.venv/bin/tox
```
