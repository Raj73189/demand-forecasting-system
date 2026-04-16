from collections.abc import Mapping
from typing import Any, Optional

from passlib.context import CryptContext
from sqlalchemy.orm import Session

from . import models
pwd_context = CryptContext(schemes=["bcrypt", "pbkdf2_sha256"], deprecated="auto")


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def get_user_by_email(db: Session, email: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.email == email.lower().strip()).first()


def create_user(db: Session, email: str, password: str) -> models.User:
    normalized_email = email.lower().strip()
    user = models.User(email=normalized_email, password_hash=get_password_hash(password), role="user")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[models.User]:
    user = get_user_by_email(db, email)
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def get_current_user(session_data: Mapping[str, Any], db: Session) -> Optional[models.User]:
    user_id = session_data.get("user_id")
    if not user_id:
        return None
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    return db.query(models.User).filter(models.User.id == user_id).first()


def is_admin(user: Optional[models.User]) -> bool:
    return bool(user and user.role == "admin")
