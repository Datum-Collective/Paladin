# Benchmarks

Measured by `scripts/benchmark.py` on Darwin arm64, 8 CPUs, Python 3.12.13, 2026-10-14 15:53:23. Load is synthetic (seeded generator), mixed Linux auth / web access / IDS lines through the real parsers, SQLite store, correlation and path engine. In-process: HTTP and network latency are not included.

| events | parse eps | ingest eps | correlate ms | graph ms | paths ms | analysis ms | end-to-end ms | confirmed steps | ranked paths |
|---|---|---|---|---|---|---|---|---|---|
| 1000 | 130467 | 227840 | 5.42 | 0.04 | 0.51 | 15.8 | 27.9 | 2 | 8 |
| 10000 | 145919 | 243188 | 55.28 | 0.04 | 0.36 | 95.3 | 204.9 | 2 | 8 |
| 50000 | 147175 | 236429 | 277.05 | 0.05 | 0.35 | 539.1 | 1090.3 | 2 | 8 |

## Graph scale (synthetic layered graph, 3 entry points, 3 crown jewels)

| nodes | edges | build ms | top-10 paths ms | min cut ms | paths found | cut cost |
|---|---|---|---|---|---|---|
| 106 | 309 | 0.3 | 10.0 | 1.2 | 10 | 11.0 |
| 501 | 1494 | 1.4 | 65.3 | 1.2 | 10 | 6.0 |
| 1986 | 5949 | 6.0 | 602.1 | 2.3 | 10 | 4.0 |
