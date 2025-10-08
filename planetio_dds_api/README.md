# Planetio DDS API

This addon exposes a minimal JSON endpoint that allows external systems to
create and immediately transmit an EUDR DDS (Due Diligence Statement) without
interacting with the Planetio user interface.  The module is intended for
system-to-system integrations that already collect the essential data required
by TRACES.

## Endpoint

| Method | Path                     | Auth | Payload type |
|--------|--------------------------|------|--------------|
| POST   | `/api/dds/minimal_submit` | user | JSON         |

Authentication uses the standard Odoo user authentication (basic auth, session
cookies or API key modules).  The user must have permissions to create
`eudr.declaration` records.

## Request body

```json
{
  "partner_id": 42,
  "activity_type": "import",
  "net_mass_kg": 1250.5,
  "hs_code": "090111",
  "operator_type": "TRADER",
  "producer_name": "Cooperativa Amazzonia",
  "lines": [
    {
      "name": "Plot 1",
      "farmer_id_code": "PLOT-001",
      "country": "BR",
      "geometry": {
        "type": "Point",
        "coordinates": [-60.123, -10.456]
      }
    }
  ]
}
```

You can either pass an existing `partner_id` or supply a `partner` object with
the fields required to create a new partner on the fly:

```json
{
  "partner": {
    "name": "Importer SpA",
    "vat": "IT12345678901",
    "country_code": "IT",
    "street": "Via Roma 1",
    "zip": "00100",
    "city": "Roma"
  },
  "net_mass_kg": 100,
  "lines": [
    {
      "farmer_name": "Juan Perez",
      "country": "PE",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [-72.1, -13.1],
            [-72.1, -13.0],
            [-72.0, -13.0],
            [-72.1, -13.1]
          ]
        ]
      }
    }
  ]
}
```

### Required fields

* `net_mass_kg`: numeric value greater than zero.
* At least one `lines` entry with a valid GeoJSON `geometry`.  Only `Point`,
  `Polygon` and `MultiPolygon` types are accepted.
* Either `partner_id` or a `partner` block with at least the partner `name`.

Optional fields map directly to the `eudr.declaration` model: `activity_type`,
`hs_code`, `operator_type`, `producer_name`, `operator_name`,
`common_name`, `product_description`, `coffee_species_id`, `product_id` and
`third_party_client_id`.

### Line fields

Each line dictionary supports the following keys: `name`, `farmer_name`,
`farmer_id_code`, `tax_code`, `country`, `region`, `municipality`, `farm_name`,
`area_ha` and the mandatory `geometry`.

## Response

A successful call returns:

```json
{
  "ok": true,
  "id": 128,
  "name": "EUDR0005",
  "dds_identifier": "2cdce080-1234-4abc-8f4f-1f746e046782",
  "reference_number": "IT.ABC.0001",
  "stage": "Sent"
}
```

If TRACES returns a verification number and the field exists on the model, the
`verification_number` attribute is also included.

Errors are returned with `ok: false` together with an `error` message and an
`error_type` of either `user_error` (validation/UserError) or
`server_error` for unexpected issues.  The transaction is rolled back when an
error is returned.

## Dependencies

* `planetio` – provides the `eudr.declaration` model and DDS submission logic.

