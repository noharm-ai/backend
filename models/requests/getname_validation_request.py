"""Request models: getname validation page (public, see docs/agents/getname-validation.md)"""

from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints

# everything here is typed by an anonymous browser: closed vocabularies where
# there is one, short bounded strings where there is not
_CODE = r"^[a-z0-9_]{1,60}$"


class GetnameValidationCheck(BaseModel):
    """One step of the test, as the page ran it"""

    id: str = Field(pattern=_CODE)
    status: Literal["passed", "failed", "warning", "skipped"]
    code: Optional[str] = Field(default=None, pattern=_CODE)
    httpStatus: Optional[int] = Field(default=None, ge=0, le=999)
    durationMs: Optional[int] = Field(default=None, ge=0, le=600000)
    detail: Optional[str] = Field(default=None, max_length=300)


class GetnameValidationEnvironment(BaseModel):
    """Where the test ran: what tells a network problem from a browser one"""

    userAgent: Optional[str] = Field(default=None, max_length=400)
    # the browser and the operating system in words ("Google Chrome 142.0.7444.60",
    # "Windows 11"), as the page worked them out
    browser: Optional[str] = Field(default=None, max_length=80)
    platform: Optional[str] = Field(default=None, max_length=80)
    pageOrigin: Optional[str] = Field(default=None, max_length=200)
    online: Optional[bool] = None
    secureContext: Optional[bool] = None
    # literal private/loopback/public ip, or a hostname (unknown before DNS)
    targetAddressSpace: Optional[
        Literal["private", "loopback", "public", "hostname"]
    ] = None
    # state of the browser's local network permissions, by permission name
    permissions: Optional[
        dict[
            Annotated[str, StringConstraints(pattern=r"^[a-z-]{1,40}$")],
            Literal["granted", "denied", "prompt"],
        ]
    ] = Field(default=None, max_length=6)
    getnameVersion: Optional[str] = Field(default=None, max_length=40)
    language: Optional[str] = Field(default=None, max_length=20)


class GetnameValidationResultRequest(BaseModel):
    """The receipt of one run of the validation page"""

    status: Literal["passed", "failed", "not_applicable"]
    diagnosis: Optional[str] = Field(default=None, pattern=_CODE)
    checks: list[GetnameValidationCheck] = Field(max_length=12)
    environment: GetnameValidationEnvironment = GetnameValidationEnvironment()
