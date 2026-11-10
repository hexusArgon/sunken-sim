"""Former name of the Mage kernel module: farm.hybrid.fire_cl is farm.hybrid.mage_cl.

The exact OpenCL kernel started with Fire and now covers Fire, Frost and Arcane.
Importing this name returns the same module object, so module state
(``_REFINE``, the worker engine) is shared.
"""
import sys

from farm.hybrid import mage_cl as _mage_cl

sys.modules[__name__] = _mage_cl
