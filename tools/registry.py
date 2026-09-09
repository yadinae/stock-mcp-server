"""
Auto-discovery tool registry for stock-mcp-server.

Scans tools/handlers/*.py for register(mcp) functions and calls them.
Inspired by go-stock (https://github.com/ArvinLovegood/go-stock) registerToolHandler pattern.
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

logger = logging.getLogger("stock-mcp")


def auto_register(mcp) -> None:
    """
    Auto-discover and register all tool handlers in tools/handlers/.

    Each handler module must export a register(mcp) function that
    takes a FastMCP instance and registers @mcp.tool() decorated functions.
    """
    handlers_dir = Path(__file__).parent / "handlers"
    if not handlers_dir.exists():
        logger.warning("tools/handlers/ directory not found, no tools registered")
        return

    package_name = "tools.handlers"
    registered = 0

    for _importer, modname, _ispkg in pkgutil.iter_modules([str(handlers_dir)]):
        full_name = f"{package_name}.{modname}"
        try:
            module = importlib.import_module(full_name)
        except Exception as e:
            logger.error("Failed to import handler module %s: %s", full_name, e)
            continue

        register_fn = getattr(module, "register", None)
        if register_fn is None or not callable(register_fn):
            logger.warning("Module %s has no register(mcp) function, skipping", full_name)
            continue

        try:
            register_fn(mcp)
            registered += 1
            logger.info("Registered handler: %s", modname)
        except Exception as e:
            logger.error("Failed to register handler %s: %s", modname, e)

    logger.info("Auto-registered %d handler modules", registered)
