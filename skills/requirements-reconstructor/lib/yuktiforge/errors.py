class YuktiForgeError(Exception):
    """Base class for all expected, user-facing errors."""


class SchemaError(YuktiForgeError):
    pass


class InvalidTransition(YuktiForgeError):
    pass


class ArtifactPathError(YuktiForgeError):
    pass


class PolicyDenied(YuktiForgeError):
    pass


class UnsupportedByAdapter(YuktiForgeError):
    pass
