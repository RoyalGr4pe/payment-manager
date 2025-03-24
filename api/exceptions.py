class UserNotFoundError(Exception):
    """Exception raised when a user is not found in the database."""
    def __init__(self, message={"message": "Username doesn't exist", "code": 3}):
        self.message = message
        super().__init__(self.message)