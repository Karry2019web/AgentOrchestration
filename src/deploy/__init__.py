"""Deployment module — migration preflight and rollout safety gates."""

from .preflight import MigrationMetadata, BackupVerification, MigrationPreflight, DestructiveMigrationError

__all__ = ["MigrationMetadata", "BackupVerification", "MigrationPreflight", "DestructiveMigrationError"]
