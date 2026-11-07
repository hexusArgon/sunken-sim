"""Conservative Fire-only backend policy, not a speculative batch-size threshold.

Limited real-search trials do not establish a GPU crossover for a full farm.
Auto chooses the exact CPU oracle; explicit hybrid keeps parity/near-tie guards.
"""
import os

def select(job):
    if (str(job.get('hero','')).strip().lower(),str(job.get('spec','')).strip().lower()) != ('mage','fire'):
        return None
    mode=str(job.get('fire_backend') or os.environ.get('FARM_FIRE_BACKEND','auto')).strip().lower()
    if mode not in ('auto','cpu','hybrid'):
        raise ValueError('fire_backend/FARM_FIRE_BACKEND must be auto, cpu or hybrid')
    return dict(requested=mode,selected='hybrid' if mode=='hybrid' else 'cpu',
                policy='explicit override' if mode!='auto' else 'conservative CPU: no validated whole-search GPU crossover',
                version='fire-scalar-v1')
