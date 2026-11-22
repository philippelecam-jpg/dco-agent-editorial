"""Test de bout en bout reel du pipeline carrousel sur une branche isolee.

Ce script publie sur Instagram. Ne jamais lancer sans autorisation explicite.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from instagram_carousel import generate, render, validate, publish
from instagram_reels import CTA, Instagram, hashtags_for, save_entry

ROOT = Path("historique/instagram/carrousels")
SOURCE = Path("tests/fixtures/article_reunions_e2e.md")


def commit_checkpoint(message):
    subprocess.run(["git", "add", str(ROOT)], check=True)
    status = subprocess.run(["git", "diff", "--cached", "--quiet"], check=False)
    if status.returncode == 0:
        return
    if status.returncode != 1:
        raise RuntimeError("Impossible de verifier les changements Git.")
    subprocess.run(["git", "commit", "-m", message], check=True)
    branch = os.environ["E2E_TARGET_BRANCH"]
    subprocess.run(["git", "push", "origin", f"HEAD:refs/heads/{branch}"], check=True)


def main():
    run_id = os.environ["GITHUB_RUN_ID"]
    branch = os.environ["E2E_TARGET_BRANCH"]
    if branch != "test/carrousel-decisions-reunions-2026-11":
        raise RuntimeError("La branche cible du test E2E est incorrecte.")
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise RuntimeError("Le workflow E2E doit etre declenche depuis main.")
    source = SOURCE.read_text(encoding="utf-8")
    folder = ROOT / f"e2e-{run_id}"
    journal = folder / "journal.json"
    if journal.exists():
        entry = json.loads(journal.read_text(encoding="utf-8"))
    else:
        package = validate(generate(source))
        entry = {
            "type": "test_pipeline_e2e",
            "source": str(SOURCE),
            "source_sha256": hashlib.sha256(source.encode("utf-8")).hexdigest(),
            "package": package,
        }
        entry["caption"] = (
            "[TEST PIPELINE DECISIONS & CO]\n\n"
            + package["legende"] + "\n\n" + CTA + "\n" + hashtags_for({})
        )
        save_entry(journal, entry)
    render(validate(entry["package"]), folder)
    commit_checkpoint("test(e2e): sauvegarder les 7 visuels et la legende")
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    repository = os.environ["GITHUB_REPOSITORY"]
    urls = [
        f"https://raw.githubusercontent.com/{repository}/{sha}/{folder}/{i}.jpg"
        for i in range(1, 8)
    ]
    def checkpoint():
        commit_checkpoint("test(e2e): journaliser la publication Meta")
    client = Instagram(os.environ["INSTAGRAM_ACCESS_TOKEN"])
    publish(client, entry, journal, urls, checkpoint=checkpoint)
    print("E2E_OK : generation Claude, rendu 7 images, upload Meta, publication et verification.")

if __name__ == "__main__":
    main()
