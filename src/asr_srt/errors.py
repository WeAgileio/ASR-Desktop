class AsrSrtError(Exception):
    """Base error shown to CLI users."""


class ValidationError(AsrSrtError):
    pass


class DependencyError(AsrSrtError):
    pass


class MediaError(AsrSrtError):
    pass


class ModelOutputError(AsrSrtError):
    pass


class MPSCompatibilityError(AsrSrtError):
    pass


class OutputExistsError(AsrSrtError):
    pass


class JobError(AsrSrtError):
    def __init__(self, phase: str, message: str):
        self.phase = phase
        super().__init__(f"{phase}: {message}")

