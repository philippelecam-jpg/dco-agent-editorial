"""Génère un aperçu local du carrousel de test, sans appel à Instagram."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from instagram_carousel import render, validate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="preview_carrousel_reunions")
    args = parser.parse_args()
    fixture = Path(__file__).with_name("carrousel_reunions.json")
    package = validate(json.loads(fixture.read_text(encoding="utf-8")))
    output = Path(args.output)
    render(package, output)
    print(f"Aperçu généré : {output.resolve()} (7 JPG, aucune publication)")

if __name__ == "__main__":
    main()
