"""eBird species catalog import and deterministic exact-name resolution."""

from __future__ import annotations

import unicodedata

import httpx
from pydantic import ValidationError

from .. import config
from ..db.repository import SpeciesRepository
from ..db.session import SessionFactory
from ..schemas import (
    SpeciesCatalogEntry,
    SpeciesLookup,
    SpeciesRecord,
    TaxonomyResolution,
)


class TaxonomySourceError(RuntimeError):
    """The external taxonomy could not be fetched or validated."""


class TaxonomyImportError(ValueError):
    """A catalog batch is ambiguous and must not be imported."""


class EbirdTaxonomyAdapter:
    """Fetch the current Simplified-Chinese eBird species taxonomy."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = config.EBIRD_BASE_URL,
        locale: str = config.EBIRD_TAXONOMY_LOCALE,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._locale = locale

    def fetch_entries(self) -> list[SpeciesCatalogEntry]:
        key = self._api_key or config.load_ebird_api_key()
        if not key:
            raise TaxonomySourceError(
                "EBIRD_API_KEY 未设置，无法下载 eBird 物种名录。"
            )
        try:
            response = httpx.get(
                f"{self._base_url}/ref/taxonomy/ebird",
                headers={"X-eBirdApiToken": key},
                params={
                    "cat": "species",
                    "fmt": "json",
                    "locale": self._locale,
                },
                timeout=config.EBIRD_TAXONOMY_TIMEOUT_S,
            )
            response.raise_for_status()
            rows = response.json()
        except httpx.TimeoutException as exc:
            raise TaxonomySourceError("下载 eBird 物种名录超时。") from exc
        except httpx.HTTPStatusError as exc:
            raise TaxonomySourceError(
                f"eBird 物种名录返回 HTTP {exc.response.status_code}。"
            ) from exc
        except httpx.RequestError as exc:
            raise TaxonomySourceError("网络连接 eBird 物种名录失败。") from exc
        except ValueError as exc:
            raise TaxonomySourceError("eBird 物种名录不是合法 JSON。") from exc

        return self.parse_rows(rows)

    @staticmethod
    def parse_rows(rows: object) -> list[SpeciesCatalogEntry]:
        if not isinstance(rows, list):
            raise TaxonomySourceError("eBird 物种名录根节点不是数组。")

        entries: list[SpeciesCatalogEntry] = []
        for row in rows:
            if not isinstance(row, dict):
                raise TaxonomySourceError("eBird 物种名录包含非对象条目。")
            if row.get("category") != "species":
                continue
            try:
                entries.append(
                    SpeciesCatalogEntry(
                        taxonomy_source="ebird",
                        taxonomy_key=row.get("speciesCode"),
                        canonical_chinese_name=row.get("comName"),
                        scientific_name=row.get("sciName"),
                    )
                )
            except ValidationError as exc:
                raise TaxonomySourceError(
                    "eBird species 条目缺少 speciesCode/comName 等必填字段。"
                ) from exc
        if not entries:
            raise TaxonomySourceError("eBird 物种名录没有 category=species 的条目。")
        return entries


class TaxonomyService:
    """Own catalog transactions and resolve names without fuzzy guessing."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def import_entries(
        self, entries: list[SpeciesCatalogEntry]
    ) -> list[SpeciesRecord]:
        keys = [
            (entry.taxonomy_source, entry.taxonomy_key) for entry in entries
        ]
        if len(set(keys)) != len(keys):
            raise TaxonomyImportError(
                "taxonomy_source/taxonomy_key values must be unique within a batch"
            )

        cleaned = [self._clean_entry(entry) for entry in entries]
        with self._session_factory.begin() as session:
            repository = SpeciesRepository(session)
            return repository.upsert_many(cleaned)

    def resolve_many(
        self, lookups: list[SpeciesLookup]
    ) -> list[TaxonomyResolution]:
        with self._session_factory() as session:
            records = SpeciesRepository(session).list_all()
        return [self._resolve(lookup, records) for lookup in lookups]

    @staticmethod
    def _clean_entry(entry: SpeciesCatalogEntry) -> SpeciesCatalogEntry:
        reserved = {
            _normalize_name(entry.canonical_chinese_name),
            _normalize_name(entry.scientific_name),
        }
        aliases: list[str] = []
        seen = set(reserved)
        for raw_alias in entry.aliases:
            alias = raw_alias.strip()
            normalized = _normalize_name(alias)
            if normalized and normalized not in seen:
                aliases.append(alias)
                seen.add(normalized)
        return entry.model_copy(update={"aliases": aliases})

    @classmethod
    def _resolve(
        cls, lookup: SpeciesLookup, records: list[SpeciesRecord]
    ) -> TaxonomyResolution:
        scientific = _normalize_name(lookup.scientific_name)
        if scientific:
            matches = [
                row
                for row in records
                if _normalize_name(row.scientific_name) == scientific
            ]
            if matches:
                return cls._resolution_for(matches, "scientific_name", lookup.scientific_name)

        label = _normalize_name(lookup.species_label)
        if not label:
            return TaxonomyResolution(
                status="unmapped", warning="未提供可解析的物种名称。"
            )

        scientific_matches = [
            row
            for row in records
            if _normalize_name(row.scientific_name) == label
        ]
        if scientific_matches:
            return cls._resolution_for(
                scientific_matches, "scientific_name", lookup.species_label
            )

        canonical_matches = [
            row
            for row in records
            if _normalize_name(row.canonical_chinese_name) == label
        ]
        if canonical_matches:
            return cls._resolution_for(
                canonical_matches, "canonical_name", lookup.species_label
            )

        alias_matches = [
            row
            for row in records
            if any(_normalize_name(alias) == label for alias in row.aliases)
        ]
        if alias_matches:
            return cls._resolution_for(alias_matches, "alias", lookup.species_label)

        shown = lookup.species_label or lookup.scientific_name or "<空>"
        return TaxonomyResolution(
            status="unmapped", warning=f"物种名录中找不到：{shown}"
        )

    @staticmethod
    def _resolution_for(
        matches: list[SpeciesRecord], matched_by: str, query: str | None
    ) -> TaxonomyResolution:
        unique = {row.id: row for row in matches}
        ids = list(unique)
        if len(ids) == 1:
            return TaxonomyResolution(
                status="resolved",
                species_id=ids[0],
                matched_by=matched_by,
                candidate_species_ids=ids,
            )
        return TaxonomyResolution(
            status="ambiguous",
            matched_by=matched_by,
            candidate_species_ids=ids,
            warning=f"名称 {query or '<空>'} 命中多个物种。",
        )


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()
