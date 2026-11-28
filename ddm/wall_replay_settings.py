"""Duration limits shared by the room picker and rolling cache."""

DEFAULT_MINUTES = 3
MAX_MINUTES = 60


def cache_minutes(value):
    return max(1, min(MAX_MINUTES, value)) if type(value) is int else DEFAULT_MINUTES
