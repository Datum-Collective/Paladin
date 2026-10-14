# Data contracts (frozen)

All ids in `scenarios/*.yaml` and `data/inventory.yaml` come from one shared name list: users, hosts, roles,
secrets, crown jewels. Synthetic data only.

## Event
```json
{"id":"e17","ts":"2024-05-14T13:10:03Z","source":"linux_auth","type":"auth_success",
 "actor":"www-data","host":"WEB-BO-01","src_ip":"185.199.110.42","dst":"WEB-BO-01",
 "outcome":"success","attack":"T1078","raw":"<original line>"}
```
`source`: linux_auth | web_access | ids_alert | json. `outcome`: success | failure | alert | info.

## Node
```json
{"id":"WEB-BO-01","kind":"host","label":"Claims portal web server","criticality":4}
```
`kind`: identity | host | secret | role | service | data | external. `criticality` 1-10.

## Edge
```json
{"id":"web-to-www","src":"internet","dst":"WEB-BO-01","technique":"T1190","p":0.4,"cost":null,
 "observed":false,"evidence":[],"mitigation":"M1050"}
```
`cost` null = uncuttable. `p` in (0,1]. `evidence` = event ids that confirmed the edge.

## Path
```json
{"id":"p1","nodes":["internet","WEB-BO-01","FILE-BO-01"],"edges":["a","b"],"p":0.12,"impact":9,
 "risk":0.108,"severity":"HIGH","tactics":["initial-access","lateral-movement"],"narrative":"..."}
```
`risk = prod(edge p) * criticality(target) / 10`, in [0,1].

## Fix
```json
{"edges":["b"],"total_cost":3,"paths_broken":2,"risk_removed_pct":84.0,
 "mitigations":[{"edge":"b","technique":"T1021","mitigation":"M1032","name":"Multi-factor Authentication"}]}
```

## Probability update
A distinct event matching an edge's `match` spec sets `observed=true` and `p' = min(0.99, p + (1-p)*0.5)`.

## Severity bands
CRITICAL >= 0.30, HIGH >= 0.10, MEDIUM >= 0.03, else LOW (constants in `analyze.py`).
