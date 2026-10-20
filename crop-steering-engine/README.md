# crop-steering-engine

The **pure, HA-independent crop-steering decision core**, extracted from
`HA-Irrigation-Strategy`'s lean engine so it can run identically inside the f2-control
add-on, a standalone async control service, a worker, or a test — **the host no longer
matters.** It is a pure-Python package with no runtime framework dependency; the
f2-control add-on imports it.

```python
from crop_steering_engine import decide, ZoneParams, ZoneSnapshot

phase, p2_threshold, fire, size_pct, reason = decide(snapshot, params)
```

`decide(s, p)` is a plain function over two dataclasses — no I/O, no Home Assistant,
deterministic. It implements the 4-phase (P0→P3) state machine, EC steering,
the anti-lockout high-EC flush (any phase), the lights-on starvation watchdog,
and the daily-volume budget cap. The IO shell (reading sensors, driving valves,
durable state, the 30-min notifier) lives in the host service, not here.

## Dev

```bash
pip install -e ".[dev]"
pytest          # offline unit tests, no hardware
ruff check .
```

This package is the foundation of the f2-control add-on, the live control service. The
agronomic upgrade (peak-VWC-target, two-loop PID, sump-measured runoff) lands here as new
pure functions, validated offline before the service ships them.
