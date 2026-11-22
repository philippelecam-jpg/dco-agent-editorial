"""Générateur de couvertures Reels Décisions & Co (1080x1920, zone sûre grille 1080x1350 centrée).

Usage :
    python reel_cover.py "Titre accrocheur" --rubrique "L'IA AU BUREAU" --episode "Épisode 3" --out cover.jpg [--image fond.jpg]

- Le titre et la rubrique sont placés dans la zone visible dans la grille du profil (recadrage 4:5 central).
- --image (optionnel) : visuel du Reel placé en fond, assombri par un dégradé bleu nuit.
Dépendance : playwright (python) avec Chromium.
"""
import argparse, base64, html, pathlib
from playwright.sync_api import sync_playwright

TPL = """<html><head><style>
*{{margin:0;box-sizing:border-box}}
body{{width:1080px;height:1920px;font-family:'Inter',sans-serif;overflow:hidden;position:relative;background:#0F172A}}
.bg{{position:absolute;inset:0;background:{bg};background-size:cover;background-position:center}}
.shade{{position:absolute;inset:0;background:linear-gradient(180deg,rgba(15,23,42,.15) 0%,rgba(15,23,42,.55) 40%,rgba(30,58,138,.92) 72%,#1E40AF 100%)}}
.ring{{position:absolute;border:2px solid rgba(255,255,255,.10);border-radius:50%;width:900px;height:900px;right:-420px;top:-380px}}
.safe{{position:absolute;left:0;right:0;top:285px;height:1350px}}
.brand{{position:absolute;top:70px;left:80px;color:#fff;font-weight:800;font-size:34px;letter-spacing:1px}}
.chip{{position:absolute;top:70px;right:80px;background:#93C5FD;color:#0F172A;font-weight:800;font-size:28px;padding:12px 26px;border-radius:40px}}
.txt{{position:absolute;left:80px;right:80px;bottom:110px}}
.rub{{color:#93C5FD;font-weight:700;font-size:30px;letter-spacing:6px}}
h1{{color:#fff;font-weight:800;font-size:{fs}px;line-height:1.05;letter-spacing:-1.5px;margin-top:22px}}
.bar{{width:120px;height:10px;border-radius:6px;background:#93C5FD;margin-top:40px}}
</style></head><body><div class='bg'></div><div class='shade'></div><div class='ring'></div>
<div class='safe'><div class='brand'>DECISIONS &amp; CO</div>{chip}
<div class='txt'><div class='rub'>{rub}</div><h1>{title}</h1><div class='bar'></div></div></div>
</body></html>"""

def render(title, rubrique, episode=None, image=None, out="cover.jpg"):
    bg = "linear-gradient(155deg,#0F172A 0%,#1E3A8A 60%,#1E40AF 100%)"
    if image:
        b64 = base64.b64encode(pathlib.Path(image).read_bytes()).decode()
        bg = f"url(data:image/jpeg;base64,{b64})"
    fs = 104 if len(title) < 40 else 88 if len(title) < 70 else 74
    chip = f"<div class='chip'>{html.escape(episode)}</div>" if episode else ""
    page = TPL.format(bg=bg, fs=fs, chip=chip, rub=html.escape(rubrique.upper()), title=html.escape(title))
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page(viewport={"width": 1080, "height": 1920})
        pg.set_content(page); pg.wait_for_timeout(300)
        pg.screenshot(path=out, type="jpeg", quality=92); b.close()
    return out

if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("title"); a.add_argument("--rubrique", default="DÉCISIONS & CO")
    a.add_argument("--episode"); a.add_argument("--image"); a.add_argument("--out", default="cover.jpg")
    x = a.parse_args(); print(render(x.title, x.rubrique, x.episode, x.image, x.out))
