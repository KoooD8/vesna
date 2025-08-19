import os
import re
import json
from typing import Any, Dict, Callable

Registry: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {}

def register(name: str):
    def _wrap(fn: Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]):
        Registry[name] = fn
        return fn
    return _wrap

__all__ = ["Registry", "register"]

