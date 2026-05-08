class AccountNotFoundError(Exception):
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"Account {account_id} not found")


class AccountCodeExistsError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Account code '{code}' already exists")


class InvalidAccountTypeError(Exception):
    def __init__(self, account_type: str) -> None:
        self.account_type = account_type
        super().__init__(f"Invalid account type: {account_type}")


class CannotDeleteSystemAccountError(Exception):
    def __init__(self, account_id: str) -> None:
        self.account_id = account_id
        super().__init__(f"Cannot delete or disable system account {account_id}")


class CannotModifyParentError(Exception):
    def __init__(self) -> None:
        super().__init__("Cannot set parent account to itself or a descendant")
