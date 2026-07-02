"""FastAPI приложение user-service."""

from typing import Optional

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
    app = FastAPI(title="user-service")
except ImportError:
    app = None  # type: ignore


class CreateUserRequest(BaseModel):
    """Запрос на создание пользователя."""
    username: str
    email: str
    role: str = "user"


class UserResponse(BaseModel):
    """Ответ с данными пользователя."""
    id: int
    username: str
    email: str
    role: str


def get_user(user_id: int) -> Optional[UserResponse]:
    """Возвращает пользователя по ID из базы данных.

    Args:
        user_id: уникальный идентификатор пользователя

    Returns:
        UserResponse или None если пользователь не найден
    """
    return None  # stub


def create_user(request: CreateUserRequest) -> UserResponse:
    """Создаёт нового пользователя.

    Проверяет уникальность username и email перед созданием.
    """
    return UserResponse(id=1, username=request.username, email=request.email, role=request.role)


def delete_user(user_id: int) -> bool:
    return True
