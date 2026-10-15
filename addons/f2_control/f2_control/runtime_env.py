"""What the controller's environment tells it about how it runs.

For now one thing: how long the safe-off on SIGTERM may take (Controller._safe_exit). The Supervisor
waits `timeout: 30` (config.yaml) after SIGTERM before it kills the app, so the default budget of
25 s leaves 5 s for the process to end. Raise the stop timeout with F2_STOP_BUDGET_S, never to less
than the budget plus 5 s.
"""
import math

STOP_BUDGET_S = 25.0


def stop_budget(env):
    """Seconds the safe-off on SIGTERM may take: F2_STOP_BUDGET_S when it is a number above 0, else
    STOP_BUDGET_S."""
    try:
        budget = float(env.get("F2_STOP_BUDGET_S") or STOP_BUDGET_S)
    except (TypeError, ValueError):
        return STOP_BUDGET_S
    return budget if math.isfinite(budget) and budget > 0 else STOP_BUDGET_S
