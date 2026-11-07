"""Discord adapter: preserve string progress/cancel/job identity around hybrid metadata.

No Discord calls, credentials, or background jobs here. Farm.execute owns the same
thread, box and status callback as before. Routing never depends on worker nickname.
"""
from __future__ import annotations


def run_job(job: dict, box: dict, tick) -> dict:
    from farm.hybrid.runner import run_job as hybrid_run_job

    backend = "Backend: проверка hybrid / CPU scheduling"

    def update(value):
        nonlocal backend
        if isinstance(value, dict):
            info = value.get("hybrid", {})
            if info.get("gpu_fights"):
                backend = (
                    f"Backend: hybrid · {info.get('device')} · {info.get('name')}"
                    " · CPU scheduling + GPU scoring; exact CPU fallback возможен"
                )
            else:
                reason = info.get("fallback") or info.get("reason") or info.get("status", "unsupported")
                backend = f"Backend: CPU · {reason}"
            print(backend, flush=True)
        else:
            # Append, do not replace/reorder the protocol's status/cancel fields.
            tick(str(value) + "\n" + backend)

    return hybrid_run_job(job, box, update)
