# Benchmarks

Measured by `scripts/benchmark.py` on Darwin arm64, 6 CPUs, Python 3.12.14, 2026-10-15 19:27:45. Load is synthetic (seeded generator), mixed Linux auth / web access / IDS lines through the real parsers, correlation and path engine. It intentionally excludes Supabase, HTTP, and network latency. Peak KiB is Python tracemalloc allocation during each run.

| events | parse eps | prepare ms | correlate + graph + paths ms | analysis ms | end-to-end ms | peak KiB | confirmed steps | ranked paths |
|---|---|---|---|---|---|---|---|---|
| 1000 | 8404 | 12.9 | 64.42 | 64.4 | 196.3 | 2800.6 | 2 | 8 |
| 10000 | 9834 | 140.7 | 533.29 | 533.3 | 1690.9 | 27133.3 | 2 | 8 |
| 50000 | 8901 | 815.8 | 2515.1 | 2515.1 | 8948.0 | 135635.6 | 2 | 8 |

## Graph scale (synthetic layered graph, 3 entry points, 3 crown jewels)

| nodes | edges | build ms | top-10 paths ms | min cut ms | paths found | cut cost | peak KiB |
|---|---|---|---|---|---|---|---|
| 106 | 309 | 1.6 | 145.5 | 7.7 | 10 | 11.0 | 873.2 |
| 501 | 1494 | 8.7 | 958.0 | 6.3 | 10 | 6.0 | 4116.6 |
| 1986 | 5949 | 41.0 | 2075.8 | 14.4 | 8 | 3.0 | 16084.1 |
