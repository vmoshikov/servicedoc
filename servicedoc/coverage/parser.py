import logging
import sqlite3
import xml.etree.ElementTree as ET
from pathlib import Path

from servicedoc.models.coverage import CoverageResult, TestFile

logger = logging.getLogger(__name__)


def parse_coverage_xml(path: Path) -> CoverageResult | None:
    try:
        tree = ET.parse(path)
        root = tree.getroot()
        overall = float(root.get("line-rate", 0)) * 100
        covered = int(root.get("lines-covered", 0))
        total = int(root.get("lines-valid", 0))
        return CoverageResult(
            overall_pct=round(overall, 1),
            covered_lines=covered,
            total_lines=total,
            report_source="coverage.xml",
        )
    except Exception as exc:
        logger.debug("Failed to parse coverage.xml: %s", exc)
        return None


def parse_coverage_sqlite(path: Path) -> CoverageResult | None:
    try:
        conn = sqlite3.connect(str(path))
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM arc WHERE hit > 0")
        covered = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM arc")
        total = cur.fetchone()[0]
        conn.close()
        pct = round(covered / total * 100, 1) if total else 0.0
        return CoverageResult(
            overall_pct=pct,
            covered_lines=covered,
            total_lines=total,
            report_source=".coverage",
        )
    except Exception as exc:
        logger.debug("Failed to parse .coverage SQLite: %s", exc)
        return None


def parse_lcov(path: Path) -> CoverageResult | None:
    covered = total = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("DA:"):
                parts = line[3:].split(",")
                if len(parts) >= 2:
                    total += 1
                    if int(parts[1]) > 0:
                        covered += 1
        if total == 0:
            return None
        return CoverageResult(
            overall_pct=round(covered / total * 100, 1),
            covered_lines=covered,
            total_lines=total,
            report_source="lcov.info",
        )
    except Exception as exc:
        logger.debug("Failed to parse lcov.info: %s", exc)
        return None


def find_and_parse(repo_path: Path) -> CoverageResult | None:
    candidates = [
        (repo_path / "coverage.xml", parse_coverage_xml),
        (repo_path / ".coverage", parse_coverage_sqlite),
        (repo_path / "lcov.info", parse_lcov),
        (repo_path / "coverage" / "lcov.info", parse_lcov),
        (repo_path / "coverage.out", None),  # Go coverage — parse separately
    ]
    for path, parser in candidates:
        if path.exists() and parser:
            result = parser(path)
            if result:
                logger.info("Found coverage report: %s (%.1f%%)", path, result.overall_pct)
                return result

    # Go: search for coverage.out
    for cov_out in repo_path.rglob("coverage.out"):
        result = _parse_go_coverage_out(cov_out)
        if result:
            return result

    return None


def _parse_go_coverage_out(path: Path) -> CoverageResult | None:
    covered = total = 0
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("mode:") or not line.strip():
                continue
            parts = line.split()
            if len(parts) >= 5:
                total += 1
                if int(parts[4]) > 0:
                    covered += 1
        if total == 0:
            return None
        return CoverageResult(
            overall_pct=round(covered / total * 100, 1),
            covered_lines=covered,
            total_lines=total,
            report_source="coverage.out",
        )
    except Exception as exc:
        logger.debug("Failed to parse coverage.out: %s", exc)
        return None
