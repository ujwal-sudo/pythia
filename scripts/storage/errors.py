"""Exceptions for the storage layer.

All failures are explicit: a typo in a path must not look like an empty
directory, because that is how the previous pipeline silently wrote to the
wrong disk.
"""


class StoreError(Exception):
    """Base class for storage failures."""


class InvalidPath(StoreError):
    """A relative path escaped the store root or was malformed."""


class NotFound(StoreError):
    """The requested object does not exist in the store."""


class BackendUnavailable(StoreError):
    """The backend cannot be used (missing binary, bad root, no credentials)."""
