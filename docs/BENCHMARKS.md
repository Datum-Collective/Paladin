# Benchmarks

Measured by `scripts/benchmark.py` on Darwin arm64, 8 CPUs, Python 3.12.13, 2026-10-14 15:47:36. Load is synthetic (seeded generator), mixed Linux auth / web access / IDS lines through the real parsers, SQLite store, correlation and path engine. In-process: HTTP and network latency are not included.

| events | parse eps | ingest eps | correlate ms | graph ms | paths ms | analysis ms | end-to-end ms | confirmed steps | ranked paths |
|---|---|---|---|---|---|---|---|---|---|
| 1000 | 131901 | 208214 | 5.77 | 0.05 | 0.8 | 16.1 | 28.5 | 2 | 8 |
| 10000 | 138173 | 245315 | 56.64 | 0.08 | 0.43 | 98.0 | 211.2 | 2 | 8 |

## Graph scale (synthetic layered graph, 3 entry points, 3 crown jewels)

| nodes | edges | build ms | top-10 paths ms | min cut ms | paths found | cut cost |
|---|---|---|---|---|---|---|
| 106 | 309 | 0.3 | 9.8 | 1.3 | 10 | 11.0 |
| 501 | 1494 | 1.5 | 67.0 | 1.2 | 10 | 6.0 |
| 1986 | 5949 | 6.1 | 607.5 | 2.5 | 10 | 4.0 |
