"""SQLAlchemy модели: User, UserGroup, user_group_membership, RefreshToken."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Table, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.config import Base


# Ассоциативная таблица для связи many-to-many между User и UserGroup
user_group_membership = Table(
    "user_group_membership",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("group_id", Integer, ForeignKey("user_groups.id"), primary_key=True),
)


class User(Base):
    """Пользователь системы."""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    username = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Связи
    groups = relationship("UserGroup", secondary=user_group_membership, back_populates="users")
    chat_sessions = relationship("ChatSession", back_populates="user")
    refresh_tokens = relationship("RefreshToken", back_populates="user", cascade="all, delete-orphan")


class UserGroup(Base):
    """Группа доступа с поддержкой иерархии (parent_id) и приоритетом."""

    __tablename__ = "user_groups"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    parent_id = Column(Integer, ForeignKey("user_groups.id"), nullable=True)
    priority = Column(Integer, default=0)

    # Связи
    parent = relationship("UserGroup", remote_side=[id], backref="children")
    users = relationship("User", secondary=user_group_membership, back_populates="groups")
    document_permissions = relationship("DocumentGroupPermission", back_populates="group")


class RefreshToken(Base):
    """Refresh токен для обновления JWT access token.

    Хранится в БД для возможности отзыва (revoke) сессий.
    """

    __tablename__ = "refresh_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False)  # SHA-256 хеш токена
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Связи
    user = relationship("User", back_populates="refresh_tokens")
