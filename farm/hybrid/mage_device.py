"""Per-engine, PID/device-isolated and byte-bounded reusable input tensors.

Budget counts exact resident tensor payload, not backend allocator/graph memory.
Calls are sequential; callers must materialize results before reusing inputs.
"""
from collections import OrderedDict, Counter
import os
import numpy as np


class DevicePool:
    def __init__(self, torch, target, max_bytes=32 << 20):
        self.torch, self.target = torch, target
        self.max_bytes = max(0, int(max_bytes))
        self.entries = OrderedDict()
        self.counts = Counter()
        self.resident_bytes = 0
        self.context = None
        self.copy_supported = True

    def clear(self):
        self.entries.clear()
        self.resident_bytes = 0
        self.counts['resident_bytes'] = 0

    def _key(self, name, array):
        context = (os.getpid(), str(self.target))
        if context != self.context:
            self.clear(); self.context = context
            self.counts['context_resets'] += 1
        return name, array.shape, str(array.dtype)

    def up(self, name, values, constant=False):
        array = np.ascontiguousarray(values, dtype=np.float32)
        key = self._key(name, array)
        hit = self.entries.pop(key, None)
        if hit is not None:
            tensor, size = hit
            self.entries[key] = hit
            if constant:
                self.counts['constant_reuses'] += 1
                return tensor
            if self.copy_supported:
                try:
                    tensor.copy_(self.torch.from_numpy(array))
                    self.counts['reuses'] += 1
                    return tensor
                except RuntimeError:
                    # Backend may not support in-place uploads. Never score stale inputs.
                    self.copy_supported = False
                    self.clear(); self.counts['copy_unsupported'] += 1
            else:
                self.clear()
        tensor = self.torch.from_numpy(array).to(self.target)
        self.counts['allocations'] += 1
        size = array.nbytes
        if self.copy_supported and size <= self.max_bytes:
            while self.entries and self.resident_bytes + size > self.max_bytes:
                _, (_, nbytes) = self.entries.popitem(last=False)
                self.resident_bytes -= nbytes
                self.counts['evictions'] += 1
            self.entries[key] = tensor, size
            self.resident_bytes += size
            self.counts['resident_bytes'] = self.resident_bytes
            self.counts['peak_bytes'] = max(self.counts['peak_bytes'], self.resident_bytes)
        else:
            self.counts['uncached_uploads'] += 1
        return tensor

    def constant(self, name, value):
        # Name includes value: constants can never alias after code/value changes.
        return self.up(('constant', name, float(value)), [value], constant=True)


def parts(tls, max_rows=512, working_bytes=64 << 20):
    """Bound padded compile graph estimate (256 float32 planes + executes).

    The resident pool has a separate exact payload budget. Backend graph caches
    are managed by torch/DirectML, not an assertion about total VRAM/RSS.
    Oversized single rows are yielded with False for exact CPU scoring.
    """
    i = 0
    while i < len(tls):
        width = 1; executes = 0; j = i
        while j < len(tls) and j - i < max_rows:
            w = max(width, len(tls[j].events))
            e = max(executes, len(tls[j].stats['executes']))
            estimate = (j - i + 1) * w * 4 * (256 + e)
            if estimate > working_bytes:
                break
            width, executes = w, e
            j += 1
        if j == i:
            yield tls[i:i+1], False
            i += 1
        else:
            yield tls[i:j], True
            i = j
