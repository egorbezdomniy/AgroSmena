class ServiceError(Exception):
    """Base exception that is safe to show in the interface."""


class ValidationError(ServiceError):
    pass


class NotFoundError(ServiceError):
    pass


class ConflictError(ServiceError):
    pass

