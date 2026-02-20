"""
Nominal data structure used by skills:

data/
    datastore2/
        01-Mine/
            <Domain>/
                YYYY/
                    MM/
                        DD/
        02-Analysis/
            <Domain>/
                YYYY/
                    MM/
                        DD/
        03-Present/
            <Domain>/
                YYYY/
                    MM/
                        DD/

Area aliases supported by this module:
- mine -> 01-Mine
- analyse/analyze/analysis -> 02-Analysis
- present -> 03-Present

How skills should use this module:
1) Import and initialize once:
    from CommonCode.FolderNavigator import FolderNavigator
    nav = FolderNavigator.from_fixed_point()

2) Resolve path for a dated write target:
    target = nav.get_date_path(
         area="mine",
         domain="News",
         value="2026/02/20",
         create=True,
    )

3) Resolve path for today's output:
    today_target = nav.get_today_path(area="present", domain="News", create=True)

4) Resolve latest existing folder for reads/fallback:
    latest = nav.latest_date_path(area="analyse", domain="News")

5) Optional discovery helpers:
    mine_root = nav.get_area_root("mine")
    domains = nav.list_domains("mine")

Use these explicit calls instead of constructing folder strings in skill code.

This keeps skill logic focused on task behavior while folder rules stay
centralized in one shared module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Iterable


DEFAULT_AREA_ALIASES: Dict[str, str] = {
    "mine": "01-Mine",
    "analyze": "02-Analysis",
    "analyse": "02-Analysis",
    "analysis": "02-Analysis",
    "present": "03-Present",
}


class FolderNavigatorError(ValueError):
    pass


@dataclass(slots=True)
class FolderNavigator:
    data_root: Path
    area_aliases: Dict[str, str] = field(default_factory=lambda: dict(DEFAULT_AREA_ALIASES))

    @classmethod
    def from_fixed_point(cls) -> "FolderNavigator":
        """Build from this module's fixed location: workspace/Skills/CommonCode."""
        openclaw_root = Path(__file__).resolve().parents[3]
        return cls(data_root=openclaw_root / "data" / "datastore2")

    @staticmethod
    def parse_date(value: str | date | datetime) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value

        cleaned = str(value).strip().replace("-", "/")
        parts = cleaned.split("/")
        if len(parts) != 3:
            raise FolderNavigatorError("Date must be YYYY/MM/DD or YYYY-MM-DD")

        try:
            year, month, day = (int(p) for p in parts)
            return date(year, month, day)
        except ValueError as exc:
            raise FolderNavigatorError("Invalid date value") from exc

    def normalize_area(self, area: str) -> str:
        cleaned = area.strip()
        if not cleaned:
            raise FolderNavigatorError("Area cannot be empty")

        lowered = cleaned.lower()
        mapped = self.area_aliases.get(lowered, cleaned)
        return mapped

    def validate_domain(self, domain: str) -> str:
        cleaned = domain.strip()
        if not cleaned:
            raise FolderNavigatorError("Domain cannot be empty")
        if "/" in cleaned or "\\" in cleaned:
            raise FolderNavigatorError("Domain cannot contain path separators")
        return cleaned

    def ensure(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_area_root(self, area: str, create: bool = False) -> Path:
        path = self.data_root / self.normalize_area(area)
        return self.ensure(path) if create else path

    def get_domain_root(self, area: str, domain: str, create: bool = False) -> Path:
        path = self.get_area_root(area, create=create) / self.validate_domain(domain)
        return self.ensure(path) if create else path

    def get_date_path(
        self,
        area: str,
        domain: str,
        value: str | date | datetime,
        create: bool = False,
    ) -> Path:
        parsed = self.parse_date(value)
        path = self.get_domain_root(area, domain, create=create) / f"{parsed.year:04d}" / f"{parsed.month:02d}" / f"{parsed.day:02d}"
        return self.ensure(path) if create else path

    def get_today_path(self, area: str, domain: str, create: bool = False) -> Path:
        return self.get_date_path(area=area, domain=domain, value=date.today(), create=create)

    def list_domains(self, area: str) -> Iterable[str]:
        area_path = self.get_area_root(area)
        if not area_path.exists():
            return []
        return sorted(p.name for p in area_path.iterdir() if p.is_dir())

    def latest_date_path(self, area: str, domain: str) -> Path | None:
        domain_root = self.get_domain_root(area, domain)
        if not domain_root.exists():
            return None

        latest: tuple[date, Path] | None = None

        for year in (p for p in domain_root.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 4):
            for month in (p for p in year.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 2):
                for day in (p for p in month.iterdir() if p.is_dir() and p.name.isdigit() and len(p.name) == 2):
                    try:
                        dt_value = date(int(year.name), int(month.name), int(day.name))
                    except ValueError:
                        continue
                    if latest is None or dt_value > latest[0]:
                        latest = (dt_value, day)

        return latest[1] if latest else None


__all__ = ["FolderNavigator", "FolderNavigatorError", "DEFAULT_AREA_ALIASES"]
