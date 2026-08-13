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

Before each write, existing contacts are resolved with `GET /contacts/{id}` (when `id` is configured) or `POST /search`. Configure `lookup_fields` and `lookup_method` to control matching:

- `sequential` (default) — try `id` via GET, then search with OR across other populated lookup fields
- `all` — every lookup field must be populated and match the same contact (AND search, or GET by `id` plus field verification)

Supported lookup fields:

| Unified field | Qomon field |
| --- | --- |
| `id` | `id` |
| `email` | `mail` |
| `external_id` | `external_id` |
| `first_name` | `firstname` |
| `last_name` | `surname` |

### Contact writes

Records are written with synchronous Qomon endpoints:

- **Create** — `POST /contacts` when no match is found; the new contact ID is returned in job state
- **Update** — `PATCH /contacts/{id}` when a match is found

Custom fields are mapped using form definitions from `GET /v1/forms/type/custom_fields` (cached once per job) into the sync API shape (`form_id`, `form_ref_id`, `data`).

## Source Authentication and Authorization

Qomon uses a static API key. Create one in the Qomon UI under account settings and use it with the `Authorization: Bearer <api_key>` header.

See the [Qomon developer docs](https://developers.qomon.com/pages/v1/getting-started.md) for details.

## Supported Streams

| Stream | Description |
| --- | --- |
| `Contacts` | Unified contacts sink with tags, custom fields, and synchronous create/update |

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
