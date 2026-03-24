"""
Abstract repository interface defining the contract for user data persistence.
"""

import abc
from typing import Optional
from app.models.domain import User

class UserRepository(abc.ABC):
    """
    Abstract Base Class defining the contract for user data persistence.

    By using an interface, we decouple the application's business logic 
    from the infrastructure layer. This architecture allows switching 
    from an in-memory store to a persistent database (e.g., PostgreSQL) 
    without modifying the service or engine layers.
    """

    @abc.abstractmethod
    def save_user(self, user: User) -> User:
        """
        Persists a User entity to the data store.

        This method handles both the initial creation of a user and 
        subsequent updates to their state (Step, Task, Status).

        Args:
            user (User): The user domain entity to be saved or updated.

        Returns:
            User: The successfully persisted User object.
        """
        pass

    @abc.abstractmethod
    def get_user(self, user_id: str) -> Optional[User]:
        """
        Retrieves a User entity from the store by its unique identifier.

        Args:
            user_id (str): The unique ID (UUID/String) of the user to fetch.

        Returns:
            Optional[User]: The User object if found, otherwise None.
        """
        pass

    @abc.abstractmethod
    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Retrieves a User entity by their email address.
        Useful for preventing duplicate registrations.

        Args:
            email (str): The email address to search for.

        Returns:
            Optional[User]: The User object if found, otherwise None.
        """
        pass