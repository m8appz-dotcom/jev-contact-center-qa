"""Package the original review UI with real recorded results; no provider requests."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from jevqa.report import leer_resultados  # noqa: E402
from jevqa.rubric import load_rubric  # noqa: E402
from jevqa.scoring import ESTADO_APROBADO  # noqa: E402


def recorded_snapshot() -> dict:
    rubric = load_rubric(str(ROOT / "rubrics/support_en.json"))
    labels = {
        item["id"]: item["label"]
        for item in json.loads((ROOT / "rubrics/support_en.json").read_text(encoding="utf-8"))["items"]
    }
    results_path = ROOT / "docs/examples/live-english/results.csv"
    scored = leer_resultados(str(results_path), rubric)
    if scored["sin_calificar"]:
        raise ValueError("Recorded results must all have a completed assessment")
    with results_path.open(encoding="utf-8-sig", newline="") as stream:
        raw = {row["id"]: row for row in csv.DictReader(stream)}
    assessments = {}
    for result in scored["calificaciones"]:
        assessments[result["id"]] = {
            "conversation": result["id"],
            "model": raw[result["id"]]["modelo"],
            "score": result["nota"],
            "outcome": "Passed" if result["estado"] == ESTADO_APROBADO else "Failed",
            "needsReview": result["revisar"],
            "criteria": [
                {
                    "label": labels[item["id"]],
                    "critical": result["items"][item["id"]]["critico"],
                    "meets": result["items"][item["id"]]["cumple"],
                    "needsReview": bool(result["items"][item["id"]]["motivos_revision"]),
                    "confidence": result["items"][item["id"]]["confianza"],
                }
                for item in rubric["items"]
            ],
        }
    if set(assessments) != {"MINI-1", "MINI-2", "MINI-3"}:
        raise ValueError("Only the three authored conversations belong in this public package")
    return {"version": 1, "assessments": assessments}


def build(destination: Path) -> None:
    """Destination is a dedicated JEV asset directory; existing files are retained."""
    review = destination / "review"
    review.mkdir(parents=True, exist_ok=True)
    public = ROOT / "demo/public"
    for name in (
        "base.css", "products.css", "ui.css", "app.js", "core.js", "data.js",
        "review-state.js", "engine-client.js", "recorded-assessment.js",
    ):
        shutil.copyfile(public / name, review / name)
    index = (public / "index.html").read_text(encoding="utf-8")
    if '<html lang="en">' not in index:
        raise ValueError("Expected the original English review page")
    (review / "index.html").write_text(
        index.replace('<html lang="en">', '<html lang="en" data-assessment-mode="recorded">', 1),
        encoding="utf-8", newline="\n",
    )
    (review / "recorded-assessments.json").write_text(
        json.dumps(recorded_snapshot(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8", newline="\n",
    )
    for name in (
        "informe_Bank_cards.html", "informe_Health_insurance.html",
        "informe_Home_internet.html", "conversations.csv", "results.csv", "evidence.json",
    ):
        shutil.copyfile(ROOT / "docs/examples/live-english" / name, destination / name)
    for name in ("workspace-desktop.jpg", "workspace-mobile.jpg"):
        shutil.copyfile(ROOT / "docs/images" / name, destination / name)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    build(parser.parse_args().destination)
