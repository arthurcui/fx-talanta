"""Bounded ASCII/HMAC protocol shared with the shadow EA; HTTPS is mandatory.

Transport authentication TTL is distinct from the two-second entry ceiling.
An authenticated receipt is a shadow result, never an execution acknowledgment.
"""

import hashlib
import hmac
import re
from dataclasses import dataclass

MAX_BODY = 32768
PATH = "/v1/shadow"


def digest(data: str) -> str:
    return hashlib.sha256(data.encode("ascii")).hexdigest()


def hex64(value):
    return bool(re.fullmatch("[0-9a-f]{64}", value))


def integer(value):
    if not re.fullmatch(r"0|[1-9][0-9]{0,14}", value):
        raise ValueError("INVALID_INTEGER")
    return int(value)


@dataclass(frozen=True)
class Frame:
    direction: str
    scope: str
    client: str
    nonce: str
    issued: int
    expires: int
    operation: str
    payload: str

    def prefix(self):
        if (
            self.direction not in {"C2S", "S2C"}
            or not hex64(self.scope)
            or not hex64(self.client)
            or not hex64(self.nonce)
            or self.operation not in {"PULL", "REPORT", "WORK", "EMPTY", "ACK", "ERROR"}
            or not 0 < self.expires - self.issued <= 5000
        ):
            raise ValueError("INVALID_FRAME")
        integer(str(self.issued))
        integer(str(self.expires))
        if any(ord(c) > 126 or (ord(c) < 32 and c not in "\t\n") for c in self.payload):
            raise ValueError("INVALID_PAYLOAD")
        return "\t".join(
            [
                "shadow/1",
                self.direction,
                self.scope,
                self.client,
                self.nonce,
                str(self.issued),
                str(self.expires),
                self.operation,
                self.payload.encode("ascii").hex() or "-",
            ]
        )

    def encode(self, key: bytes) -> bytes:
        if not 32 <= len(key) <= 64:
            raise ValueError("INVALID_KEY")
        prefix = self.prefix()
        mac = hmac.new(key, prefix.encode("ascii"), hashlib.sha256).hexdigest()
        result = (prefix + "\t" + mac).encode("ascii")
        if len(result) > MAX_BODY:
            raise ValueError("PAYLOAD_TOO_LARGE")
        return result

    @classmethod
    def decode(cls, raw, key, *, direction, scope, client, now, nonce=None):
        if len(raw) > MAX_BODY:
            raise ValueError("PAYLOAD_TOO_LARGE")
        try:
            f = raw.decode("ascii").split("\t")
            if len(f) != 10 or f[0] != "shadow/1":
                raise ValueError("INVALID_FRAME")
            payload = "" if f[8] == "-" else bytes.fromhex(f[8]).decode("ascii")
            result = cls(*f[1:5], integer(f[5]), integer(f[6]), f[7], payload)
            if not hmac.compare_digest(result.encode(key), raw):
                raise ValueError("AUTHENTICATION_FAILURE")
            if (result.direction, result.scope, result.client) != (direction, scope, client):
                raise ValueError("ROUTE_MISMATCH")
            if nonce is not None and result.nonce != nonce:
                raise ValueError("RESPONSE_MISMATCH")
            # Small, explicit transport clock tolerance; not quote-age credit.
            if result.issued > now + 2000 or result.expires <= now:
                raise ValueError("TRANSPORT_EXPIRED")
            return result
        except (UnicodeError, TypeError) as error:
            raise ValueError("INVALID_FRAME") from error
