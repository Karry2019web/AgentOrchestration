"""Trace query service with nested filter depth validation."""

import json
from typing import Dict, List, Optional, Any

# Maximum allowed depth for nested filters in trace queries.
# Prevents deep recursion / stack exhaustion from maliciously crafted queries.
MAX_FILTER_DEPTH = 5


class TraceQueryError(Exception):
    """Raised when a trace query is invalid."""
    pass


class NestedFilterDepthError(TraceQueryError):
    """Raised when a nested filter exceeds the maximum allowed depth."""
    def __init__(self, depth: int, max_depth: int = MAX_FILTER_DEPTH):
        super().__init__(
            f"Nested filter depth {depth} exceeds maximum allowed depth {max_depth}. "
            f"Simplify query structure."
        )


class TraceQueryService:
    """Shared service for validating and executing trace queries."""

    @staticmethod
    def validate_filter_depth(filter_dict: Dict, current_depth: int = 0) -> None:
        """Recursively validate nested filter depth.

        Args:
            filter_dict: The filter dictionary to validate.
            current_depth: Current recursion depth.

        Raises:
            NestedFilterDepthError: If depth exceeds MAX_FILTER_DEPTH.
        """
        if current_depth > MAX_FILTER_DEPTH:
            raise NestedFilterDepthError(current_depth)

        for key, value in filter_dict.items():
            if key in ("$and", "$or", "$not", "$nor"):
                if isinstance(value, list):
                    for sub_filter in value:
                        if isinstance(sub_filter, dict):
                            TraceQueryService.validate_filter_depth(
                                sub_filter, current_depth + 1
                            )
                elif isinstance(value, dict):
                    TraceQueryService.validate_filter_depth(
                        value, current_depth + 1
                    )
            elif isinstance(value, dict):
                # Nested field path — could be an operator or sub-filter
                TraceQueryService.validate_filter_depth(value, current_depth + 1)

    @staticmethod
    def parse_and_validate_query(body: Dict) -> Dict:
        """Parse and validate a trace query request body.

        Validates:
            - Required fields are present
            - Nested filter depth does not exceed MAX_FILTER_DEPTH
            - Filter structure is a dict

        Args:
            body: The raw request body.

        Returns:
            The validated query dict.

        Raises:
            TraceQueryError: If validation fails.
        """
        if not isinstance(body, dict):
            raise TraceQueryError("Request body must be a JSON object")

        trace_type = body.get("trace_type")
        if not trace_type:
            raise TraceQueryError("Missing required field: trace_type")

        filters = body.get("filters", {})
        if not isinstance(filters, dict):
            raise TraceQueryError("'filters' must be a JSON object")

        # Validate nested filter depth
        TraceQueryService.validate_filter_depth(filters)

        # Validate limit
        limit = body.get("limit", 100)
        if not isinstance(limit, int) or limit < 1 or limit > 10000:
            raise TraceQueryError("'limit' must be an integer between 1 and 10000")

        return {
            "trace_type": trace_type,
            "filters": filters,
            "limit": limit,
            "offset": body.get("offset", 0),
            "sort": body.get("sort", "-timestamp"),
        }

    @staticmethod
    def execute_query(params: Dict) -> List[Dict]:
        """Execute a validated trace query against the trace store.

        This is a placeholder that returns mock results.
        In production, this would query the actual trace database.

        Args:
            params: Validated query parameters from parse_and_validate_query.

        Returns:
            List of trace entries matching the query.
        """
        # Placeholder: return empty results
        # Production implementation would query the trace store
        return []
