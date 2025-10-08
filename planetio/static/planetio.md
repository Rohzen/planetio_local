### Flowchart base
```mermaid
flowchart TD
  subgraph S1[Data sources]
    A1[Odoo: incoming shipments / lots] --> S
    A2[Odoo: production lots / MO] --> S
    A3[External: CSV/Excel/JSON API] --> S
  end

  S["EUDR Lot Staging<br/>(model: eudr.lot)"]
  N_S["Campi chiave:<br/>- origin_country (ISO2)<br/>- hs_code, net_mass_kg<br/>- producer_name/country (se noti)<br/>- plots (GeoJSON features)<br/>- upstream dds_reference / dds_identifier (se presenti)"]
  S -.-> N_S

  S --> B["Build EUDR Declaration<br/>(seleziona lotti, valida, consolida)"]
  B --> C{Seleziona modalità DDS}

  C -->|A - Single commodity| M1["Mode A<br/>Single DDS, 1 commodity<br/>(comportamento attuale)"]
  C -->|B - Multi commodities| M2["Mode B<br/>Single DDS, N commodities<br/>(1..* producers per commodity,<br/>ogni producer = 1 FeatureCollection)"]
  C -->|C - Trader refs| M3["Mode C<br/>Trader DDS con<br/>associated statements<br/>(senza geometrie)"]

  %% Raggruppamenti/consolidì
  M1 --> G1["Consolidamento unico:<br/>HS, descrizione, peso, 1 producer/plots"]
  M2 --> G2["Raggruppa per commodity:<br/>- merge lotti compatibili<br/>- per ciascun producer: bundle dei suoi plot"]
  M3 --> G3["Estrai references dai lotti:<br/>dds_identifier / referenceNumber"]

  %% Invio
  G1 --> X[SOAP Submit TRACES]
  G2 --> X
  G3 --> X

  X --> R{Response}
  R -->|200 OK| OK1["Salva dds_identifier + WS_REQUEST_ID;<br/>schedula fetch referenceNumber/pdf"]
  R -->|Business errors| E1["Mostra elenco violazioni;<br/>lascia la dichiarazione modificabile"]
  R -->|Fault| E2["Log raw,<br/>warning non bloccante + retry"]

  %% Post
  OK1 --> L["Link dichiarazione ↔ lotti usati<br/>(audit, evitare riuso)"]
  L --> D["Distribuzione a valle:<br/>se trader, crea dichiarazioni Mode C<br/>referenziando DDS a monte"]

  %% Stile nota
  classDef note fill:#fff,stroke-dasharray: 5 5,stroke:#999;
  class N_S note;
