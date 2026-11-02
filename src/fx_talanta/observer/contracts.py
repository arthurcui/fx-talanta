import ntpath
from hashlib import sha256
from typing import Annotated

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

    @model_validator(mode="after")
    def validate_binding(self):
        if self.account.environment != "PAPER" or self.account.venue != "SIMULATOR":
            raise ValueError("only synthetic observation bindings are enabled in this increment")
        for path in (self.terminal_path, self.data_path):
            drive, _ = ntpath.splitdrive(path)
            if not drive or not ntpath.isabs(path):
                raise ValueError("terminal/data paths must be absolute Windows paths")
        if not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("observation symbols must be nonempty and unique")
        return self

    def fingerprint(self):
        return sha256(self.model_dump_json().encode()).hexdigest()
