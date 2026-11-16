"""Print installed runtime versions and CUDA memory; never download model weights."""
from __future__ import annotations

import importlib
import json
import sys

result = {"python": sys.version.split()[0], "packages": {}, "cuda_available": False}
for name in ("torch", "safetensors", "transformers", "accelerate"):
    try:
        module = importlib.import_module(name)
        result["packages"][name] = getattr(module, "__version__", "installed")
        if name == "torch":
            result["cuda_available"] = module.cuda.is_available()
            result["gpus"] = [
                {"name": module.cuda.get_device_name(index),
                 "vram_gib": round(module.cuda.get_device_properties(index).total_memory / 2**30, 2)}
                for index in range(module.cuda.device_count())
            ]
    except Exception as exc:
        result["packages"][name] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result, ensure_ascii=False, indent=2))
