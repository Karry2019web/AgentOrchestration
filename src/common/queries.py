"""Trace query filter guard — validates nested filter depth."""

from typing import Any, Dict, List


class QueryFilterDepthError(Exception):
    """Raised when a trace query filter exceeds the maximum nesting depth."""
    def __init__(self, depth: int, max_depth: int):
        super().__init__(f"Query filter depth {depth} exceeds maximum allowed depth {max_depth}")
        self.depth = depth
        self.max_depth = max_depth


class TraceQueryGuard:
    """Validates trace query filter structures against nesting depth limits.

    Guards against deeply nested or recursive filter definitions that could
    cause excessive resource consumption during query processing.
    """

    MAX_FILTER_DEPTH = 5

    def __init__(self, max_depth: int = MAX_FILTER_DEPTH):
        self.max_depth = max_depth

    def validate(self, filters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a trace query filter dictionary.

        Returns the validated filter dict on success.
        Raises QueryFilterDepthError if nesting exceeds max_depth.

        Args:
            filters: The filter dictionary to validate.

        Returns:
            The validated filter dictionary (unchanged).

        Raises:
            QueryFilterDepthError: If filter nesting exceeds max_depth.
        """
        self._check_depth(filters, depth=0)
        return filters

    def _check_depth(self, obj: Any, depth: int) -> None:
        """Recursively check the nesting depth of a filter structure.

        Args:
            obj: The object to inspect (dict, list, or leaf value).
            depth: Current recursion depth.

        Raises:
            QueryFilterDepthError: If depth exceeds max_depth.
        """
        if depth > self.max_depth:
            raise QueryFilterDepthError(depth, self.max_depth)

        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, (dict, list)):
                    self._check_depth(value, depth + 1)
                elif key in ("$and", "$or", "$not"):
                    if isinstance(value, list):
                        for item in value:
                            self._check_depth(item, depth + 1)
                    elif isinstance(value, dict):
                        self._check_depth(value, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                self._check_depth(item, depth + 1)


# Shared singleton
trace_query_guard = TraceQueryGuard()
