"""Shared exceptions for research pipeline."""


class ResearchJobCancelled(Exception):
    """User requested cancellation; stop without treating as a failure."""
