"""Artifact Retention — Hold-aware deletion guard with legal/investigation hold support."""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class HoldType:
    """Types of holds that can prevent artifact deletion."""
    LEGAL = "legal"
    INVESTIGATION = "investigation"
    COMPLIANCE = "compliance"


class ArtifactRetention:
    """Manages artifact retention with hold-aware deletion predicates.

    Artifacts with active holds are excluded from automatic deletion
    even if their retention window has expired. Held expired artifacts
    are reported separately in a retention report.
    """

    def __init__(self):
        self._artifacts: Dict[str, Dict[str, Any]] = {}  # artifact_id -> metadata
        self._holds: Dict[str, Dict[str, Any]] = {}  # artifact_id -> hold_info
        self._default_retention_days = 30

    def store_artifact(
        self,
        artifact_id: str,
        data: Any,
        retention_days: Optional[int] = None,
        metadata: Optional[Dict] = None,
    ) -> None:
        """Store an artifact with optional custom retention period."""
        self._artifacts[artifact_id] = {
            "id": artifact_id,
            "data": data,
            "created_at": time.time(),
            "retention_days": retention_days or self._default_retention_days,
            "metadata": metadata or {},
        }

    def get_artifact(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        return self._artifacts.get(artifact_id)

    def apply_hold(self, artifact_id: str, hold_type: str, reason: str, applied_by: str = "system") -> bool:
        """Apply a hold to prevent an artifact from being deleted."""
        if artifact_id not in self._artifacts:
            return False
        self._holds[artifact_id] = {
            "artifact_id": artifact_id,
            "hold_type": hold_type,
            "reason": reason,
            "applied_by": applied_by,
            "applied_at": time.time(),
            "active": True,
        }
        logger.info(f"Hold applied to artifact {artifact_id}: {hold_type} - {reason}")
        return True

    def remove_hold(self, artifact_id: str) -> bool:
        """Remove the hold from an artifact."""
        if artifact_id not in self._holds:
            return False
        self._holds[artifact_id]["active"] = False
        self._holds[artifact_id]["removed_at"] = time.time()
        logger.info(f"Hold removed from artifact {artifact_id}")
        return True

    def is_held(self, artifact_id: str) -> bool:
        """Check if an artifact has an active hold."""
        hold = self._holds.get(artifact_id)
        return hold is not None and hold.get("active", False)

    def get_hold_info(self, artifact_id: str) -> Optional[Dict[str, Any]]:
        """Get hold information for an artifact."""
        return self._holds.get(artifact_id)

    def get_expired_artifacts(self) -> List[Dict[str, Any]]:
        """Get all artifacts whose retention window has expired."""
        now = time.time()
        expired = []
        for artifact_id, artifact in self._artifacts.items():
            expires_at = artifact["created_at"] + (artifact["retention_days"] * 86400)
            if now >= expires_at:
                expired.append(artifact)
        return expired

    def delete_expired(self) -> Dict[str, Any]:
        """Delete expired artifacts that are NOT on hold.

        Returns a report of:
        - deleted: artifacts that were removed
        - held_skipped: expired artifacts that were held and NOT deleted
        """
        now = time.time()
        deleted = []
        held_skipped = []

        for artifact_id, artifact in list(self._artifacts.items()):
            expires_at = artifact["created_at"] + (artifact["retention_days"] * 86400)
            if now < expires_at:
                continue  # Not yet expired

            if self.is_held(artifact_id):
                held_skipped.append({
                    "artifact_id": artifact_id,
                    "hold_type": self._holds[artifact_id]["hold_type"],
                    "reason": self._holds[artifact_id]["reason"],
                    "expired_at": expires_at,
                })
                logger.info(
                    f"Artifact {artifact_id} expired but held "
                    f"({self._holds[artifact_id]['hold_type']}): skipped deletion"
                )
                continue

            # Delete the expired, non-held artifact
            del self._artifacts[artifact_id]
            deleted.append({
                "artifact_id": artifact_id,
                "expired_at": expires_at,
            })

        report = {
            "deleted_count": len(deleted),
            "deleted": deleted,
            "held_skipped_count": len(held_skipped),
            "held_skipped": held_skipped,
        }

        if held_skipped:
            logger.warning(
                f"Retention report: {len(deleted)} deleted, "
                f"{len(held_skipped)} held expired artifacts remain"
            )
        else:
            logger.info(f"Retention cleanup: {len(deleted)} artifacts deleted")

        return report

    def list_holds(self, active_only: bool = True) -> List[Dict[str, Any]]:
        """List all holds, optionally filtering to active ones only."""
        holds = list(self._holds.values())
        if active_only:
            holds = [h for h in holds if h.get("active", False)]
        return holds

    def count_artifacts(self) -> int:
        return len(self._artifacts)

    def count_active_holds(self) -> int:
        return sum(1 for h in self._holds.values() if h.get("active", False))
