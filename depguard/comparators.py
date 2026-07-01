"""Ecosystem-vetted version comparators (DECISIONS.md §1.2 comparator policy).

Exactly four ecosystems are decidable: npm and crates.io (semver 2.0), Go (module
semver — a leading ``v`` is accepted and ``+incompatible`` is build metadata), and
PyPI (PEP440 via ``packaging``). Any other ecosystem raises ``LookupError``: a
missing vetted comparator means containment is a judgment call, and the corpus
excludes those records outright (§1.2, v1.3.0).
"""

from __future__ import annotations

import semver
from packaging.version import InvalidVersion, Version


class VersionParseError(ValueError):
    """A version string does not parse under its ecosystem's vetted comparator."""


class _ComparatorBase:
    ecosystem: str

    def key(self, version: str):
        raise NotImplementedError

    def eq(self, a: str, b: str) -> bool:
        return self.key(a) == self.key(b)

    def lt(self, a: str, b: str) -> bool:
        return self.key(a) < self.key(b)

    def le(self, a: str, b: str) -> bool:
        return self.key(a) <= self.key(b)

    def gt(self, a: str, b: str) -> bool:
        return self.key(a) > self.key(b)

    def ge(self, a: str, b: str) -> bool:
        return self.key(a) >= self.key(b)

    def sort(self, versions: list[str]) -> list[str]:
        return sorted(versions, key=self.key)


class _SemverComparator(_ComparatorBase):
    def __init__(self, ecosystem: str, strip_v: bool = False):
        self.ecosystem = ecosystem
        self._strip_v = strip_v

    def key(self, version: str):
        v = version
        if self._strip_v and v.startswith("v"):
            v = v[1:]
        try:
            parsed = semver.Version.parse(v)
        except (ValueError, TypeError) as exc:
            raise VersionParseError(
                f"{version!r} is not valid semver for ecosystem {self.ecosystem}"
            ) from exc
        # semver precedence already ignores build metadata in comparisons, but
        # Version equality does not — strip it so eq() matches precedence.
        return parsed.replace(build=None)


class _Pep440Comparator(_ComparatorBase):
    ecosystem = "PyPI"

    def key(self, version: str):
        try:
            return Version(version)
        except InvalidVersion as exc:
            raise VersionParseError(f"{version!r} is not valid PEP440") from exc


_COMPARATORS: dict[str, _ComparatorBase] = {
    "npm": _SemverComparator("npm"),
    "crates.io": _SemverComparator("crates.io"),
    "Go": _SemverComparator("Go", strip_v=True),
    "PyPI": _Pep440Comparator(),
}


def get_comparator(ecosystem: str) -> _ComparatorBase:
    """Return the vetted comparator for an ecosystem, or raise LookupError.

    Uses canonical OSV ecosystem casing (schemas/ecosystem_system_map.json).
    """
    try:
        return _COMPARATORS[ecosystem]
    except KeyError:
        raise LookupError(
            f"no vetted comparator for ecosystem {ecosystem!r} — "
            "excluded from the corpus (DECISIONS.md §1.2)"
        ) from None
