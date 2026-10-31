class DomainError(Exception):
    def __init__(self, message: str, status_code: int = 409):
        self.message = message
        self.status_code = status_code


def require_found(value, entity: str):
    if value is None:
        raise DomainError(f"{entity} not found", 404)
    return value
