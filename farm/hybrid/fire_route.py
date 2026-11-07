"""One public Fire backend: hybrid. CPU oracle/planner/fallback remain internal."""
import os

def select(job):
    if (str(job.get('hero','')).strip().lower(),str(job.get('spec','')).strip().lower()) != ('mage','fire'):
        return None
    mode=str(job.get('fire_backend') or os.environ.get('FARM_FIRE_BACKEND','hybrid')).strip().lower()
    if mode not in ('hybrid','auto','cpu','staged','cpu-staged'):
        raise ValueError('Fire has one backend: hybrid; legacy auto/cpu/staged normalize to hybrid')
    legacy_staged=('fire_cpu_staged' in job or 'FARM_FIRE_CPU_STAGED' in os.environ)
    return dict(requested=mode,selected='hybrid',policy='unified Fire hybrid',version='fire-hybrid-only-v1',
                normalized=mode!='hybrid' or legacy_staged,legacy_staged_switch_ignored=legacy_staged)
