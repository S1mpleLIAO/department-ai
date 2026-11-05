from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
Username = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")]
Password = Annotated[str, StringConstraints(min_length=12, max_length=128)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Strict):
    username: Username
    password: Annotated[str, StringConstraints(min_length=1, max_length=128)]


class UserCreate(Strict):
    username: Username
    displayName: Name
    companyId: str
    password: Password


class UserUpdate(Strict):
    displayName: Name
    companyId: str
    active: bool
    superadmin: bool = False
    revision: int


class Profile(Strict):
    displayName: Name


class ChangePassword(Strict):
    currentPassword: str = Field(min_length=1, max_length=128)
    password: Password


class ResetPassword(Strict):
    password: Password


class Group(Strict):
    name: Name
    description: str = Field(default="", max_length=255)
    actions: list[str] = Field(max_length=64)
    revision: int | None = None


class Grant(Strict):
    spaceId: str
    groupId: str


class Grants(Strict):
    grants: list[Grant] = Field(max_length=100)
    revision: int



class Company(Strict):
    name: Name


class RenameCompany(Company):
    previousName: Name
