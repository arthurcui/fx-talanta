import ntpath
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import Field, model_validator

from fx_talanta.domain.models import AccountIdentity, FrozenModel, Identifier, Text


def windows_path(value):
    return ntpath.normcase(ntpath.normpath(value))


class Binding(FrozenModel):
    account: AccountIdentity
    terminal_path: Text
    data_path: Text
    expected_build: Annotated[int, Field(gt=0)]
    expected_currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "USD"
    symbols: tuple[Identifier, ...] = ("EURUSD", "USDJPY")
    tick_max_age_seconds: Annotated[int, Field(ge=1, le=300)] = 5
    call_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 5
    max_failures: Annotated[int, Field(ge=1, le=10)] = 3
    backoff_seconds: Annotated[int, Field(ge=1, le=300)] = 2
    source: Literal["FIXTURE", "MT5"] = "FIXTURE"
    expected_company: Text | None = None
    expected_margin_mode: Literal[0, 1, 2] | None = None
    permissions_confirmed: bool = False
    permission_evidence: Text | None = None
    sdk_version: Text = "5.0.6231"
    history_hours: Annotated[int, Field(ge=1, le=24)] = 1

    @model_validator(mode="after")
    def validate_binding(self):
        if self.account.environment != "PAPER":
            raise ValueError("observer requires PAPER")
        if self.source == "FIXTURE" and self.account.venue != "SIMULATOR":
            raise ValueError("fixture reader requires SIMULATOR")
        if self.source == "MT5":
            if self.account.venue != "BROKER_DEMO":
                raise ValueError("MT5 reader requires BROKER_DEMO")
            if not self.expected_company or self.expected_margin_mode is None:
                raise ValueError("pin terminal company and account margin mode")
            if "expected_currency" not in self.model_fields_set:
                raise ValueError("demo currency must be supplied explicitly")
            if not self.account.login.isdecimal():
                raise ValueError("MT5 account login must be numeric")
        for path in (self.terminal_path, self.data_path):
            drive, _ = ntpath.splitdrive(path)
            if not drive or not ntpath.isabs(path):
                raise ValueError("terminal/data paths must be absolute Windows paths")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("observation symbols must be nonempty and unique")
        return self

    def fingerprint(self):
        return sha256(self.model_dump_json().encode()).hexdigest()

    def require_permissions(self):
        if not self.permissions_confirmed or not self.permission_evidence:
            raise ValueError("broker Python/data permissions need explicit evidence")
