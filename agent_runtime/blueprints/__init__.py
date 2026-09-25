"""Permanent compatibility package for profile promotion."""

from .resolve import promote_profile_to_persona

__layer__ = "models"

__all__ = ["promote_profile_to_persona"]
