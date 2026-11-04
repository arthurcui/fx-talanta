"""Trusted local activation manifest for one bounded demo campaign.

Hashes bind evidence; they do not prove its truth. The operator must validate the
independent time evidence and operating artifacts before calling this constructor.
Tick/receipt offset fitting is explicitly not an authority for clock mapping.
There is no HTTP activation endpoint or provider-qualification override.
"""

from copy import deepcopy
from dataclasses import asdict, dataclass

from fx_talanta.connected_shadow.inputs import canonical_hash
from fx_talanta.demo.acceptance_budget import AcceptanceBudget, hex64
from fx_talanta.shadow.store import canonical
from fx_talanta.shadow.wire import digest


@dataclass(frozen=True)
class QuoteTimePolicy:
    scope: str
    offset_ms: int
    starts_ms: int
    expires_ms: int
    evidence_sha256: str
    source_kind: str

    def __post_init__(self):
        if (
            not hex64(self.scope)
            or not hex64(self.evidence_sha256)
            or self.evidence_sha256 == "0" * 64
            or self.source_kind
            not in {"BROKER_TIME_DECLARATION", "INDEPENDENT_EVENT_AND_NATIVE_CLOCK"}
            or any(type(x) is not int for x in (self.offset_ms, self.starts_ms, self.expires_ms))
            or abs(self.offset_ms) > 50_400_000
            or self.starts_ms <= 0
            or not 0 < self.expires_ms - self.starts_ms <= 900_000
        ):
            raise ValueError("QUALIFIED_BROKER_TIME_POLICY_REQUIRED")

    def age_upper(self, raw_tick_ms, now_ms, error_ms):
        if (
            any(type(x) is not int for x in (raw_tick_ms, now_ms, error_ms))
            or not 0 <= error_ms <= 100
            or now_ms - error_ms < self.starts_ms
            or now_ms + error_ms >= self.expires_ms
            or raw_tick_ms - self.offset_ms > now_ms - error_ms
            or raw_tick_ms - self.offset_ms < self.starts_ms
        ):
            raise ValueError("QUOTE_TIME_UNVERIFIED")
        return now_ms + error_ms - (raw_tick_ms - self.offset_ms)

    def bind_capture(self, capture):
        """Create a new derived artifact; never overwrite the original capture.

        Calendar/time evidence must already be independently verified. This only
        binds that trusted policy to matching raw broker stamps and an account.
        It does not qualify providers, strategy inputs or quote delivery latency.
        """
        expected = capture.get("capture_sha256")
        if (
            expected != canonical_hash({k: v for k, v in capture.items() if k != "capture_sha256"})
            or capture.get("account_scope") != self.scope
            or capture.get("execution_enabled") is not False
            or type(capture.get("sdk_time_offset_seconds")) is not int
            or capture["sdk_time_offset_seconds"] * 1000 != self.offset_ms
            or not hex64(capture.get("clock_evidence_sha256", ""))
            or capture["clock_evidence_sha256"] == "0" * 64
        ):
            raise ValueError("TIME_POLICY_CAPTURE_BINDING")
        result = deepcopy(capture)
        quotes = list(result["quotes"].values())
        if result.get("conversion"):
            quotes.append(result["conversion"])
        if not quotes:
            raise ValueError("TIME_POLICY_QUOTES_REQUIRED")
        for quote in quotes:
            upper = self.age_upper(
                quote["raw_tick_ms"], result["measured_at_ms"], result["clock_error_ms"]
            )
            if quote["tick_ms"] != quote["raw_tick_ms"] - self.offset_ms:
                raise ValueError("TIME_POLICY_CAPTURE_MAPPING_CONFLICT")
            quote["age_ms"] = result["measured_at_ms"] - quote["tick_ms"]
            quote["age_upper_ms"] = upper
        result.update(
            source_capture_sha256=expected,
            timestamp_mapping_qualified=True,
            time_policy_evidence=self.source_kind + ":" + self.evidence_sha256,
            time_policy_sha256=digest(canonical(asdict(self))),
            qualification_scope="BOUNDED_EXECUTION_ONLY",
            qualified_for_trading=False,
        )
        result.pop("capture_sha256")
        result["capture_sha256"] = canonical_hash(result)
        return result


@dataclass(frozen=True)
class DemoActivation:
    scope: str
    release: str
    policy: str
    budget_hash: str
    time_policy: QuoteTimePolicy
    operating_evidence: str
    starts_ms: int
    expires_ms: int

    def validate(self, budget, release, policy):
        if (
            not isinstance(budget, AcceptanceBudget)
            or not isinstance(self.time_policy, QuoteTimePolicy)
            or any(
                not hex64(v) or v == "0" * 64
                for v in (
                    self.scope,
                    self.release,
                    self.policy,
                    self.budget_hash,
                    self.operating_evidence,
                )
            )
            or self.scope != budget.binding["scope"]
            or self.time_policy.scope != self.scope
            or self.release != release
            or self.policy != policy
            or self.budget_hash != budget.binding_hash
            or type(self.starts_ms) is not int
            or type(self.expires_ms) is not int
            or self.starts_ms != budget.plan.starts_ms
            or self.expires_ms != budget.plan.expires_ms
            or self.time_policy.starts_ms > self.starts_ms
            or self.time_policy.expires_ms < self.expires_ms + 60_000
        ):
            raise ValueError("DEMO_ACTIVATION_BINDING_INVALID")
        return digest(canonical(asdict(self)))

    def entry_open(self, now, error=0):
        return (
            type(now) is int
            and type(error) is int
            and 0 <= error <= 100
            and self.starts_ms <= now - error
            and now + error < self.expires_ms
        )

    def native_manifest(self):
        # Trusted deployment file; never accepted from the HTTP work channel.
        return "\t".join(
            map(
                str,
                (
                    "BOUNDED_DEMO_ACTIVATION_1",
                    self.scope,
                    self.release,
                    self.policy,
                    self.budget_hash,
                    self.time_policy.evidence_sha256,
                    self.operating_evidence,
                    self.starts_ms,
                    self.expires_ms,
                    self.time_policy.offset_ms,
                    self.time_policy.expires_ms,
                ),
            )
        )
