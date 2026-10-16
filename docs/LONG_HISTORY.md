# Optional InfluxDB history

In Rooms & hardware, Long history stays on Home Assistant Recorder until an
administrator selects InfluxDB, supplies a connection and saves it. The save
tests a bounded read query before replacing the existing connection. Use an
account/token with read-only access. An empty result still proves the endpoint
accepted the query; it does not prove that the intended probe is archived.

Version 1 uses the InfluxQL `/query` endpoint and a database, with optional
username/password. Version 2 uses Flux `/api/v2/query`, a bucket, organisation
and token. The defaults match Home Assistant's unit measurement, `value` field
and `entity_id` tag without its `sensor.` domain, scoped by the `domain` tag to
`sensor`. Clear the domain tag only for an archive schema that does not use it.
A fixed measurement and custom
field/tag can be entered; tick the full entity ID option when the tag includes
the domain. An explicit measurement is needed when a sensor has no unit and
the archive does not use its entity ID as the measurement.

The explorer's recorded-history loader uses the selected source. Errors and
empty responses fall back to Recorder with a visible warning. Queries return
mean/min/max at no more than 1000 points per sensor and 4 mapped room sensors
per request, over at most 366 days. A request has an eight-second total deadline,
two-megabyte response limit per sensor and one concurrent request per room.
There is no arbitrary query field, write endpoint or browser connection to
InfluxDB. The integration generates all query text and validates room membership
on the server. Attribute-rich daily event timelines still use Recorder.

Saved passwords and tokens are never returned to the browser, published as
entity attributes or included in upstream error messages. They live in a room
Home Assistant Store and therefore its backups; secure those backups. A blank
secret field on the setup page retains the saved secret. Selecting Recorder
disables queries and keeps the connection for a later switch back.

API references: [InfluxQL query API](https://docs.influxdata.com/influxdb/v1/api/query/)
and [Flux query API](https://docs.influxdata.com/influxdb/v2/api/query/).
