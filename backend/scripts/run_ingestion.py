"""Offline ETL entrypoint. Idempotent: truncate + reload all four sources (A1).

Usage: python scripts/run_ingestion.py
"""

import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import SessionLocal
from app.ingestion.pdf_loader import ingest_pdf
from app.ingestion.qrc_loader import ingest_qrc
from app.ingestion.xlsx_loader import ingest_xlsx
from app.repositories import rule_repository

logging.basicConfig(level=settings.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("run_ingestion")


def _resolve(path_str: str) -> str:
    p = Path(path_str)
    if not p.is_absolute():
        p = (Path(__file__).resolve().parents[1] / p).resolve()
    return str(p)


def main() -> None:
    xlsx_path = _resolve(settings.XLSX_PATH)
    pdf_path = _resolve(settings.PDF_PATH)
    pptx_path = _resolve(settings.PPTX_PATH)
    data_dir = _resolve(settings.DATA_DIR)
    Path(data_dir).mkdir(parents=True, exist_ok=True)

    for label, path in [("XLSX", xlsx_path), ("PDF", pdf_path), ("PPTX", pptx_path)]:
        if not Path(path).exists():
            log.error("%s not found at %s", label, path)
            sys.exit(1)

    # The PDF loader shells out to poppler. Fail here with something actionable
    # rather than deep inside the parser with a bare FileNotFoundError.
    if shutil.which(settings.PDFTOTEXT_BIN) is None:
        log.error(
            "'%s' not found on PATH. PDF ingestion needs pdftotext, from either "
            "poppler-utils or Xpdf:\n"
            "  macOS         brew install poppler\n"
            "  Ubuntu/WSL    sudo apt-get install -y poppler-utils\n"
            "  Windows       winget install --id oschwartz10612.Poppler\n"
            "                (or download the Xpdf tools and add the folder to PATH —\n"
            "                 Git for Windows often bundles one in mingw64/bin already)\n"
            "Then check with: pdftotext -v",
            settings.PDFTOTEXT_BIN,
        )
        sys.exit(1)

    session = SessionLocal()
    try:
        log.info("Ingesting DESC / WBS / COT from %s", xlsx_path)
        xlsx_counts = ingest_xlsx(session, xlsx_path)
        log.info("xlsx counts: %s", xlsx_counts)

        log.info("Ingesting DCCS export from %s (this shells out to pdftotext)", pdf_path)
        pdf_counts = ingest_pdf(session, pdf_path, data_dir)
        log.info("pdf counts: %s", pdf_counts)

        log.info("Ingesting QRC rulebook from %s", pptx_path)
        rule_count = ingest_qrc(session, pptx_path)
        log.info("rule_chunks: %d", rule_count)

        rule_repository.load_cache(session)

        log.info("Ingestion complete.")
        log.info(
            "Summary — DESC: %d, WBS: %d, COT: %d, DCCS history: %d, case_parties: %d, rule_chunks: %d",
            xlsx_counts["desc"], xlsx_counts["wbs"], xlsx_counts["cot"],
            pdf_counts["dccs_search_results"], pdf_counts["case_parties"], rule_count,
        )
    finally:
        session.close()


if __name__ == "__main__":
    main()
