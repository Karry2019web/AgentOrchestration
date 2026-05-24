"""Trace Explorer — Service layer for querying execution traces with nested filter depth guard."""

from typing import Any, Dict, List, Optional


MAX_FILTER_DEPTH = 3


class FilterDepthError(ValueError):
    """Raised when a filter query exceeds the maximum allowed nesting depth."""
    pass


def validate_filter_depth(filters: Any, depth: int = 0) -> None:
    """Recursively validate that filter nesting does not exceed MAX_FILTER_DEPTH.
    
    Args:
        filters: The filter structure to validate (dict, list, or leaf value).
        depth: Current recursion depth (caller should omit).
    
    Raises:
        FilterDepthError: If nesting depth exceeds MAX_FILTER_DEPTH.
    """
    if depth > MAX_FILTER_DEPTH:
        raise FilterDepthError(
            f"Filter nesting depth {depth} exceeds maximum allowed depth of {MAX_FILTER_DEPTH}"
        )

    if isinstance(filters, dict):
        for key, value in filters.items():
            # Skip operator-only keys (and, or, not) — they logically deepen nesting
            if key in ("and", "or", "not") and isinstance(value, (dict, list)):
                validate_filter_depth(value, depth + 1)
            elif isinstance(value, (dict, list)):
                # Nested comparison / sub-filter
                validate_filter_depth(value, depth + 1)
    elif isinstance(filters, list):
        for item in filters:
            if isinstance(item, (dict, list)):
                validate_filter_depth(item, depth + 1)


class TraceExplorer:
    """Service for querying orchestration execution traces with safety guards."""

    def __init__(self):
        self._traces: Dict[str, List[Dict[str, Any]]] = {}

    def query(self, filters: Optional[Dict] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Query traces with optional filters.
        
        Args:
            filters: Filter criteria (max nesting depth: MAX_FILTER_DEPTH).
            limit: Maximum number of results to return.
            offset: Number of results to skip.
        
        Returns:
            List of trace records matching the query.
        
        Raises:
            FilterDepthError: If filter nesting exceeds MAX_FILTER_DEPTH.
            ValueError: If limit or offset are invalid.
        """
        if filters is not None:
            validate_filter_depth(filters)

        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        all_traces = []
        for agent_id, traces in self._traces.items():
            for trace in traces:
                if filters and not self._matches(trace, filters):
                    continue
                all_traces.append(trace)

        all_traces.sort(key=lambda t: t.get("timestamp", 0), reverse=True)
        return all_traces[offset:offset + limit]

    def record(self, agent_id: str, trace: Dict[str, Any]) -> None:
        """Record a new trace entry."""
        if agent_id not in self._traces:
            self._traces[agent_id] = []
        self._traces[agent_id].append(trace)

    def get_by_id(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get a single trace by ID."""
        for traces in self._traces.values():
            for trace in traces:
                if trace.get("id") == trace_id:
                    return trace
        return None

    def _matches(self, trace: Dict[str, Any], filters: Dict) -> bool:
        """Check if a trace matches the given filter criteria."""
        for key, condition in filters.items():
            if key in ("and", "or", "not"):
                if key == "and":
                    if not all(self._matches(trace, sub) for sub in condition):
                        return False
                elif key == "or":
                    if not any(self._matches(trace, sub) for sub in condition):
                        return False
                elif key == "not":
                    if self._matches(trace, condition):
                        return False
            else:
                trace_value = trace.get(key)
                if isinstance(condition, dict) and not any(
                    k in condition for k in ("and", "or", "not", "eq", "neq", "gt", "gte", "lt", "lte", "in", "contains")
                ):
                    # Nested sub-filter
                    if not isinstance(trace_value, dict) or not self._matches(trace_value, condition):
                        return False
                elif isinstance(condition, dict):
                    if not self._evaluate(trace_value, condition):
                        return False
                elif trace_value != condition:
                    return False
        return True

    def _evaluate(self, trace_value: Any, condition: Dict[str, Any]) -> bool:
        """Evaluate a comparison condition against a trace value."""
        for op, target in condition.items():
            if op == "eq":
                if trace_value != target:
                    return False
            elif op == "neq":
                if trace_value == target:
                    return False
            elif op == "gt":
                if not (trace_value is not None and trace_value > target):
                    return False
            elif op == "gte":
                if not (trace_value is not None and trace_value >= target):
                    return False
            elif op == "lt":
                if not (trace_value is not None and trace_value < target):
                    return False
            elif op == "lte":
                if not (trace_value is not None and trace_value <= target):
                    return False
            elif op == "in":
                if trace_value not in target:
                    return False
            elif op == "contains":
                if target not in (trace_value or ""):
                    return False
        return True


# Module-level singleton
_explorer: Optional[TraceExplorer] = None


def get_explorer() -> TraceExplorer:
    global _explorer
    if _explorer is None:
        _explorer = TraceExplorer()
    return _explorer
