# Online pull throughput and deadline feasibility

Measured on 11 November 2026. The live database remains at **5,000 pulls and
119,597 sign-ups**. This optimization used **120 GET status requests and zero
pull requests**. The UCB multiplier remains 0.05 (`exploration=0.005`). The saved
stage target remains 5,000 and the saved online switch remains false.

## Rules and implementation

The project handout, page 3, requires one sequential driver, at least 0.25 seconds
between calls, and at most five requests per second across the entire group.
Spacing is implemented between actual call starts. Each response finishes before
the next call can begin; there is no concurrency or accumulated burst allowance.

Previously, the client waited another 0.25 seconds after each response. With an
HTTP/processing duration of 0.168 seconds, that produces roughly 0.418 seconds per
pull, or 2.39 pulls/second. The new scheduler credits the time spent receiving and
saving the response toward the 0.25-second interval:

```text
Old cycle: HTTP/processing duration + 0.25 seconds
New cycle: max(HTTP/processing duration, 0.25 seconds)
```

The clock is rechecked after every sleep, the next interval starts from the actual
dispatch time, and calls sharing a client are serialized. A newly acquired driver
waits an initial interval even if its client was constructed earlier. The existing
one-second cooldown after an uncertain response, request UUID/counter recovery,
post-wait deadline check, budget cap, SQLite FULL transactions, and per-event log
fsync remain in place. The supplied `server_pull.py` was not modified.

## Measurements

### Completed live stage, before optimization

The 3,800 real pulls from 21:38:30 to 22:05:00 Singapore time took 1,589.47 seconds:

| Metric | Result |
|---|---:|
| Overall live rate | 2.391 pulls/second |
| Mean completion interval | 418.19 ms |
| Median completion interval | 376.10 ms |
| 95th-percentile completion interval | 607.01 ms |
| Mean interval less the old mandatory wait | 168.19 ms |

The last value is an inference about combined HTTP/processing time, not a direct
measurement of network latency. The old event log records `pull_attempt` before
the pacing wait, so attempt-to-completion durations include that wait.

A separate 300-iteration local benchmark used the actual model, two SQLite FULL
transactions and three flushed/fsynced JSONL events per synthetic result in
temporary files. It averaged **0.73 ms**, with a **1.99 ms** 95th percentile. It
excluded HTTP, deliberate pacing, and progress printing. Local persistence is
small relative to the observed cycle; weakening durability is unnecessary.

### Authenticated status-only comparison

From 22:19:23 to 22:20:01 Singapore time, four blocks of 30 requests ran in the
order old/new/new/old. Both schedulers used the same supplied helper, server,
credentials, timeout, interval, and verified TLS connection setup. Every response
was checked against the unchanged group totals.

| Metric | Old scheduler | New scheduler |
|---|---:|---:|
| Requests measured | 60 | 60 |
| Mean start interval | 358.94 ms | 277.93 ms |
| Status throughput | 2.79 requests/s | 3.60 requests/s |
| Median start interval | 347.45 ms | 253.85 ms |
| Mean HTTP/helper duration | 105.45 ms | 129.13 ms |
| Mean TCP/TLS connection setup | 42.99 ms | 61.89 ms |

The optimized sample includes a 1.62-second request with 1.57 seconds spent in
connection setup; it is retained in the average. Across all 120 calls, the shortest
start interval was **250.25 ms** and a closed one-second window contained at most
**four** requests. All responses retained `PullsUsed=5000`, `NetReward=119597`.

The supplied helper opened a new connection for every measured request. Connection
reuse could be investigated later, but changing the transport is unnecessary for
this first optimization. Most request durations already fit inside the 0.25-second
spacing allowance. Keeping the helper preserves its established recovery behavior.

The status test is short and does not include the server's pull-processing cost.
Its 3.60 requests/second is **not** a measured optimized live-pull rate. Differences
between the status baseline and the earlier live rate also reflect changing
network/server conditions; use the alternating status blocks for the direct
before/after comparison.

## Can the remaining budget finish?

At **11 November, 22:20 Singapore time**, 97.65 hours remained until
**15 November 2026, 23:59 Singapore time**. The remaining 995,000 pulls required a
sustained average of **2.8304 pulls/second**, including pauses and recovery.

| Sustained rate | Hours required | Time left for interruptions at that start time |
|---|---:|---:|
| 2.391/s, previous live run | 115.6 | Misses by 18.0 hours |
| 3.0/s | 92.1 | 5.5 hours |
| 3.2/s | 86.4 | 11.3 hours |
| 3.598/s, status benchmark rate | 76.8 | 20.8 hours |
| 4.0/s, nominal pacing ceiling | 69.1 | 28.6 hours |

A replay estimate takes each historical completion interval, subtracts the old
0.25-second completion-based wait, and clamps the result to 0.25 seconds. It
predicts **3.68 pulls/second**, or **75.1 hours** for the remaining budget. This
assumes the same latency distribution, no additional downtime, and comparable
server processing under faster traffic. It is a projection, not a live result.

There is therefore a credible path to finishing with this scheduler. For planning,
3.2 pulls/second provides more margin for latency variation than assuming the
four-per-second ceiling. Recalculate with the actual start time, and verify the
sustained live rate in the next separately authorized stage. Include machine
sleep, network outages, retries and review pauses; do not add parallel drivers or
reduce the 0.25-second interval to compensate for lost time.

## Verification and artifacts

- Nine new timing tests cover fast/slow responses, local processing time, early
  wakeups, custom intervals, status/pull sharing, retry cooldown and identity,
  dispatch guards, preconstructed clients, and callers sharing one client.
- The complete standard-library suite passes **52 tests**. Phase 3's fake-server
  checks pass, including unchanged real database contents and exact target caps.
- The [raw benchmark and projections](../../phase3/results/pacing_benchmark.json)
  contain timings and counters only, without credentials or authentication headers.
- Python on this machine used `SSL_CERT_FILE=/etc/ssl/cert.pem` to load the existing
  system CA bundle; certificate and hostname verification stayed enabled.
