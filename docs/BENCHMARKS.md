# Benchmarks

Measured by `scripts/benchmark.py` on Darwin arm64, 8 CPUs, Python 3.12.13, 2026-10-14 15:29:26. Load is synthetic (seeded generator), mixed Linux auth / web access / IDS lines through the real parsers, SQLite store, correlation and path engine. In-process: HTTP and network latency are not included.

| events | parse eps | ingest eps | correlate ms | graph ms | paths ms | analysis ms | end-to-end ms | confirmed steps | ranked paths |
|---|---|---|---|---|---|---|---|---|---|
| 1000 | 137956 | 212692 | 5.64 | 0.04 | 0.52 | 15.2 | 27.1 | 2 | 8 |
| 10000 | 143664 | 228395 | 54.67 | 0.04 | 0.36 | 94.5 | 207.9 | 2 | 8 |
| 50000 | 148701 | 242532 | 275.77 | 0.05 | 0.38 | 537.0 | 1079.4 | 2 | 8 |

## Graph scale (synthetic layered graph, 3 entry points, 3 crown jewels)

| nodes | edges | build ms | top-10 paths ms | min cut ms | paths found | cut cost |
|---|---|---|---|---|---|---|
| 106 | 309 | 0.3 | 3.1 | 1.2 | 10 | 11.0 |
| 501 | 1494 | 1.4 | 19.3 | 1.2 | 10 | 6.0 |
| 1986 | 5949 | 6.0 | 165.0 | 2.3 | 10 | 4.0 |
