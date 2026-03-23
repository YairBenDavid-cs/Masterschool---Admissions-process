from typing import Dict, Optional
from app.models.domain import User
from app.repository.base import UserRepository
from app.core.logging_config import get_logger

# Initialize the logger for the repository layer
logger = get_logger(__name__)

class InMemoryUserRepository(UserRepository):
    """
    In-memory implementation of the UserRepository using Python dictionaries.

    This implementation serves as a volatile data store for the admissions 
    system. It utilizes a primary index for ID-based lookups and a 
    secondary index for email-based lookups to ensure O(1) complexity.
    """

    def __init__(self) -> None:
        """
        Initializes the internal storage structures.
        """
        self._users: Dict[str, User] = {}
        self._email_to_id: Dict[str, str] = {}
        logger.info("In-memory user repository has been initialized.")

    def save_user(self, user: User) -> User:
        """
        Persists or updates a user in the in-memory store.

        Args:
            user (User): The user entity to persist.

        Returns:
            User: The persisted user entity.
        """
        logger.debug(f"Persistence request for User ID: {user.id} ({user.email})")
        
        self._users[user.id] = user
        self._email_to_id[user.email] = user.id
        
        logger.info(f"User {user.id} successfully saved to store.")
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """
        Retrieves a user by their unique identifier.

        Args:
            user_id (str): The unique ID of the user.

        Returns:
            Optional[User]: The user entity if found, None otherwise.
        """
        user = self._users.get(user_id)
        if not user:
            logger.warning(f"Lookup failed: User with ID {user_id} not found.")
        return user

    def get_user_by_email(self, email: str) -> Optional[User]:
        """
        Retrieves a user by their email address using the secondary index.

        Args:
            email (str): The email address to look up.

        Returns:
            Optional[User]: The user entity if found, None otherwise.
        """
        user_id = self._email_to_id.get(email)
        if not user_id:
            logger.debug(f"Email lookup miss: {email} is not registered.")
            return None
            
        return self.get_user(user_id)