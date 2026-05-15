"""Public dataclasses mirroring the on-the-wire JSON shapes."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

SPEC_VERSION: str = "1.0"
"""jpzip protocol version this SDK targets."""

DEFAULT_BASE_URL: str = "https://jpzip.nadai.dev"
"""Production CDN origin."""


@dataclass(frozen=True, slots=True)
class Town:
    """One element of :class:`ZipcodeEntry.towns`."""

    town: str
    kana: str
    roma: str
    note: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Town":
        return cls(
            town=raw.get("town", ""),
            kana=raw.get("kana", ""),
            roma=raw.get("roma", ""),
            note=raw.get("note"),
        )


@dataclass(frozen=True, slots=True)
class ZipcodeEntry:
    """One logical zipcode entry as published by the CDN."""

    prefecture: str
    prefecture_kana: str
    prefecture_roma: str
    prefecture_code: str
    city: str
    city_kana: str
    city_roma: str
    city_code: str
    towns: tuple[Town, ...] = field(default_factory=tuple)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ZipcodeEntry":
        towns = tuple(Town.from_dict(t) for t in raw.get("towns", []))
        return cls(
            prefecture=raw.get("prefecture", ""),
            prefecture_kana=raw.get("prefecture_kana", ""),
            prefecture_roma=raw.get("prefecture_roma", ""),
            prefecture_code=raw.get("prefecture_code", ""),
            city=raw.get("city", ""),
            city_kana=raw.get("city_kana", ""),
            city_roma=raw.get("city_roma", ""),
            city_code=raw.get("city_code", ""),
            towns=towns,
        )


@dataclass(frozen=True, slots=True)
class Endpoints:
    """The ``endpoints`` block of ``/meta.json``."""

    group: str
    prefix: str

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Endpoints":
        return cls(group=raw.get("group", ""), prefix=raw.get("prefix", ""))


@dataclass(frozen=True, slots=True)
class Meta:
    """Parsed ``/meta.json`` payload."""

    version: str
    generated_at: str
    spec_version: str
    total_zipcodes: int
    prefix_count: int
    by_pref: dict[str, int]
    data_source: str
    endpoints: Endpoints

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Meta":
        return cls(
            version=raw.get("version", ""),
            generated_at=raw.get("generated_at", ""),
            spec_version=raw.get("spec_version", ""),
            total_zipcodes=int(raw.get("total_zipcodes", 0)),
            prefix_count=int(raw.get("prefix_count", 0)),
            by_pref=dict(raw.get("by_pref", {})),
            data_source=raw.get("data_source", ""),
            endpoints=Endpoints.from_dict(raw.get("endpoints", {})),
        )


def parse_dict(raw: dict[str, Any]) -> dict[str, ZipcodeEntry]:
    """Decode a ``/g/*.json`` or ``/p/*.json`` payload."""

    return {zip_: ZipcodeEntry.from_dict(entry) for zip_, entry in raw.items()}


__all__ = [
    "DEFAULT_BASE_URL",
    "Endpoints",
    "Meta",
    "SPEC_VERSION",
    "Town",
    "ZipcodeEntry",
    "parse_dict",
]
