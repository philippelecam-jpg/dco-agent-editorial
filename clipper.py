#!/usr/bin/env python3
"""
D&Co — Clipping Engine
Pipeline : dco-agent-editorial

Recherche des vidéos YouTube sur les thèmes D&Co,
sélectionne les meilleurs moments via Claude (IA),
et génère des clips courts au format YouTube Shorts.

Usage :
  python clipper.py                          # tous les thèmes
  python clipper.py --theme transformation_ia
  python clipper.py --theme ia_agent --max-clips 5
  python clipper.py --config custom.yaml
"""

import os
import re
import sys
import json
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

import yaml
import anthropic
from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
try:
    from youtube_transcript_api._errors import NoTranscriptFound, TranscriptsDisabled
except ImportError:
    from youtube_transcript_api import NoTranscriptFound, TranscriptsDisabled

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────

def load_config(config_path: str = "clipping_config.yaml") -> dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> logging.Logger:
    log_cfg = config.get("logging", {})
    level = getattr(logging, log_cfg.get("level", "INFO"))
    log_file = log_cfg.get("log_file", "./outputs/clipping.log")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    return logging.getLogger("dco-clipper")


# ─────────────────────────────────────────────────────────────
# RECHERCHE YOUTUBE
# ─────────────────────────────────────────────────────────────

class YouTubeSearcher:
    def __init__(self, config: dict, logger: logging.Logger):
        # API Key simple pour la recherche publique YouTube
        # (les credentials OAuth sont réservés à l'upload dans le pipeline Shorts)
        self.service = build(
            "youtube", "v3",
            developerKey=os.environ["YOUTUBE_API_KEY"],
        )
        self.cfg = config["search"]
        self.logger = logger

    def search_videos(self, keyword: str, language: str = "fr") -> list[dict]:
        """Recherche des vidéos YouTube pour un mot-clé donné."""
        self.logger.info(f"Recherche YouTube : '{keyword}'")
        params = {
            "part": "snippet",
            "q": keyword,
            "type": "video",
            "videoDuration": "medium",      # 4–20 min
            "order": "relevance",
            "maxResults": self.cfg["max_results_per_keyword"],
            "relevanceLanguage": language,
        }
        if self.cfg.get("language_filter"):
            params["relevanceLanguage"] = language

        response = self.service.search().list(**params).execute()
        video_ids = [item["id"]["videoId"] for item in response.get("items", [])]

        if not video_ids:
            return []

        # Récupérer les métadonnées complètes (durée, vues)
        details = self.service.videos().list(
            part="snippet,contentDetails,statistics",
            id=",".join(video_ids),
        ).execute()

        videos = []
        for item in details.get("items", []):
            duration_s = self._parse_duration(
                item.get("contentDetails", {}).get("duration", "PT0S")
            )
            if duration_s == 0:
                continue
            view_count = int(item["statistics"].get("viewCount", 0))
            published_at = item["snippet"]["publishedAt"]

            # Filtres qualité
            if duration_s < self.cfg["min_duration_seconds"]:
                continue
            if duration_s > self.cfg["max_duration_seconds"]:
                continue
            if view_count < self.cfg["min_view_count"]:
                continue
            if not self._is_recent(published_at, self.cfg["published_within_days"]):
                continue

            videos.append({
                "video_id": item["id"],
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "published_at": published_at,
                "duration_s": duration_s,
                "view_count": view_count,
                "url": f"https://www.youtube.com/watch?v={item['id']}",
            })

        self.logger.info(f"  → {len(videos)} vidéos retenues après filtres")
        return videos

    @staticmethod
    def _parse_duration(iso_duration: str) -> int:
        """Convertit ISO 8601 duration en secondes (ex: PT4M30S → 270)."""
        match = re.match(
            r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration
        )
        if not match:
            return 0
        h = int(match.group(1) or 0)
        m = int(match.group(2) or 0)
        s = int(match.group(3) or 0)
        return h * 3600 + m * 60 + s

    @staticmethod
    def _is_recent(published_at: str, max_days: int) -> bool:
        pub = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        delta = datetime.now(timezone.utc) - pub
        return delta.days <= max_days


# ─────────────────────────────────────────────────────────────
# TRANSCRIPTION
# ─────────────────────────────────────────────────────────────

class Transcriber:
    def __init__(self, config: dict, logger: logging.Logger):
        self.cfg = config["transcription"]
        self.cache_dir = Path(config["storage"]["transcript_cache_dir"])
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def get_transcript(self, video_id: str) -> Optional[list[dict]]:
        """Retourne la transcription segmentée [{text, start, duration}]."""
        cache_file = self.cache_dir / f"{video_id}.json"
        if cache_file.exists():
            self.logger.debug(f"Transcript en cache : {video_id}")
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)

        transcript = self._fetch_youtube_transcript(video_id)

        if transcript is None and self.cfg.get("fallback_to_whisper"):
            transcript = self._fetch_whisper_transcript(video_id)

        if transcript:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(transcript, f, ensure_ascii=False, indent=2)

        return transcript

    def _fetch_youtube_transcript(self, video_id: str) -> Optional[list[dict]]:
        """
        Méthode 1 : sous-titres via yt-dlp (fichiers .vtt).
        Contourne le blocage des IPs cloud de GitHub Actions.
        """
        import tempfile, shutil
        tmp_dir = tempfile.mkdtemp(prefix="dco_subs_")
        try:
            url = f"https://www.youtube.com/watch?v={video_id}"
            cmd = [
                "yt-dlp",
                "--skip-download",           # pas de vidéo, juste les sous-titres
                "--write-auto-subs",         # sous-titres auto-générés
                "--write-subs",              # sous-titres manuels aussi
                "--sub-langs", "fr,en,fr-FR,en-US",
                "--convert-subs", "vtt",
                "--no-check-certificates",
                "--user-agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "--add-header", "Accept-Language:fr-FR,fr;q=0.9,en;q=0.8",
                "--retries", "5",
                "-o", f"{tmp_dir}/{video_id}.%(ext)s",
                url,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            # Chercher un fichier VTT téléchargé
            vtt_files = sorted(Path(tmp_dir).glob("*.vtt"))
            if not vtt_files:
                self.logger.warning(f"  Pas de sous-titres VTT : {video_id}")
                if result.stderr:
                    self.logger.debug(f"  yt-dlp stderr : {result.stderr[-300:]}")
                return None

            # Préférer français si disponible
            chosen = next(
                (f for f in vtt_files if ".fr" in f.name or "fr-FR" in f.name),
                vtt_files[0]
            )
            segments = self._parse_vtt(chosen.read_text(encoding="utf-8"))
            self.logger.info(
                f"  Transcript VTT OK : {video_id} ({len(segments)} segments, {chosen.name})"
            )
            return segments

        except Exception as e:
            self.logger.error(f"  Erreur yt-dlp sous-titres : {e}")
            return None
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @staticmethod
    def _parse_vtt(vtt_text: str) -> list[dict]:
        """Parse un fichier WebVTT en liste de segments [{text, start, duration}]."""
        import re as _re
        segments = []
        # Regex pour les blocs de sous-titres VTT
        pattern = _re.compile(
            r"(\d{2}:\d{2}:\d{2}[.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[.,]\d{3})"
            r"[^\n]*\n([\s\S]*?)(?=\n\n|\Z)",
            _re.MULTILINE,
        )

        def ts_to_sec(ts: str) -> float:
            ts = ts.replace(",", ".")
            parts = ts.split(":")
            h, m, s = float(parts[0]), float(parts[1]), float(parts[2])
            return h * 3600 + m * 60 + s

        import html as _html
        seen_texts = set()
        for match in pattern.finditer(vtt_text):
            start_ts, end_ts, raw_text = match.groups()
            # Nettoyer balises HTML et tags VTT
            text = _re.sub(r"<[^>]+>", "", raw_text).strip()
            # Décoder les entités HTML (&nbsp; &amp; &lt; etc.)
            text = _html.unescape(text)
            text = _re.sub(r"\s+", " ", text).strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            start = ts_to_sec(start_ts)
            end = ts_to_sec(end_ts)
            segments.append({
                "text": text,
                "start": start,
                "duration": max(0.1, end - start),
            })

        return segments

    def _fetch_whisper_transcript(self, video_id: str) -> Optional[list[dict]]:
        """
        Méthode 2 (fallback) : transcription Whisper sur l'audio.
        Rarement utile en CI (yt-dlp audio aussi bloqué), mais gardé pour
        usage local ou runner auto-hébergé.
        """
        try:
            import whisper
            audio_path = f"/tmp/{video_id}.mp3"
            subprocess.run(
                [
                    "yt-dlp", "-x", "--audio-format", "mp3",
                    "--no-check-certificates",
                    "--user-agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "--retries", "3",
                    "-o", audio_path,
                    f"https://youtu.be/{video_id}",
                ],
                check=True, capture_output=True, timeout=120,
            )
            model = whisper.load_model(self.cfg.get("whisper_model", "base"))
            result = model.transcribe(audio_path, language="fr")
            Path(audio_path).unlink(missing_ok=True)
            segments = [
                {"text": s["text"], "start": s["start"],
                 "duration": s["end"] - s["start"]}
                for s in result["segments"]
            ]
            self.logger.info(f"  Transcript Whisper OK : {video_id}")
            return segments
        except Exception as e:
            self.logger.error(f"  Whisper échoué : {e}")
            return None

    @staticmethod
    def build_text_window(
        transcript: list[dict], start: float, end: float
    ) -> str:
        """Extrait le texte d'une fenêtre temporelle."""
        return " ".join(
            seg["text"] for seg in transcript
            if seg["start"] >= start and seg["start"] < end
        ).strip()

    @staticmethod
    def full_text(transcript: list[dict]) -> str:
        return " ".join(seg["text"] for seg in transcript)


# ─────────────────────────────────────────────────────────────
# SÉLECTION IA DES MOMENTS (Claude)
# ─────────────────────────────────────────────────────────────

class AISelector:
    def __init__(self, config: dict, logger: logging.Logger):
        self.cfg = config["ai_selection"]
        self.clip_cfg = config["clipping"]
        self.logger = logger
        self.client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )

    def select_best_moments(
        self,
        transcript: list[dict],
        video_meta: dict,
        theme: dict,
        max_clips: int = 3,
    ) -> list[dict]:
        """
        Demande à Claude d'identifier les N meilleurs moments à clipper.
        Retourne une liste de {start, end, score, reason, caption}.
        """
        full_text = Transcriber.full_text(transcript)
        duration = video_meta["duration_s"]
        clip_min = self.clip_cfg["clip_duration_min"]
        clip_max = self.clip_cfg["clip_duration_max"]
        criteria = "\n".join(f"- {c}" for c in self.cfg["selection_criteria"])
        avoid = "\n".join(f"- {c}" for c in self.cfg["avoid_criteria"])

        prompt = f"""Tu es l'assistant éditorial de Décisions & Co (D&Co), cabinet de conseil en transformation IA pour les PME et ETI.

Tu analyses la transcription d'une vidéo YouTube pour identifier les meilleurs moments à extraire en clips courts (format YouTube Shorts, {clip_min}–{clip_max} secondes).

**Vidéo analysée :**
- Titre : {video_meta['title']}
- Chaîne : {video_meta['channel']}
- Durée totale : {duration}s
- Thème éditorial D&Co : {theme['label']}

**Critères de sélection (moments à retenir) :**
{criteria}

**Critères d'exclusion (moments à éviter) :**
{avoid}

**Transcription complète :**
{full_text[:6000]}

**Ta mission :**
Identifie exactement {max_clips} moment(s) distincts, espacés d'au moins 30 secondes, chacun d'une durée de {clip_min} à {clip_max} secondes.

Réponds UNIQUEMENT en JSON valide, sans texte avant ou après :
{{
  "clips": [
    {{
      "start": <float: secondes depuis début>,
      "end": <float: secondes depuis début>,
      "score": <float 0.0-1.0: pertinence pour l'audience D&Co>,
      "reason": "<string: pourquoi ce moment est précieux>",
      "caption": "<string: accroche LinkedIn/X max 200 caractères pour ce clip>"
    }}
  ]
}}"""

        self.logger.info(f"  Analyse IA Claude pour : {video_meta['title'][:60]}")
        response = self.client.messages.create(
            model=self.cfg["model"],
            max_tokens=self.cfg["max_tokens"],
            messages=[{"role": "user", "content": prompt}],
        )

        raw = response.content[0].text.strip()
        # Nettoyer si Claude entoure de ```json
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
            clips = data.get("clips", [])
            # Filtrer sous le seuil de pertinence
            threshold = self.clip_cfg["relevance_threshold"]
            clips = [c for c in clips if c.get("score", 0) >= threshold]
            self.logger.info(f"  → {len(clips)} clip(s) sélectionné(s) par Claude")
            return clips
        except json.JSONDecodeError as e:
            self.logger.error(f"  JSON Claude invalide : {e}\nRaw : {raw[:200]}")
            return []

    def generate_caption(self, clip_info: dict, theme: dict) -> str:
        """Génère une accroche sociale pour le clip."""
        return clip_info.get("caption", "")


# ─────────────────────────────────────────────────────────────
# TÉLÉCHARGEMENT & DÉCOUPE VIDÉO
# ─────────────────────────────────────────────────────────────

class VideoProcessor:
    def __init__(self, config: dict, logger: logging.Logger):
        self.cfg = config
        self.clip_cfg = config["clipping"]
        self.storage_cfg = config["storage"]
        self.output_dir = Path(self.storage_cfg["output_dir"])
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def download_video(self, video_id: str) -> Optional[Path]:
        """Télécharge la vidéo source avec yt-dlp."""
        tmp_path = Path(f"/tmp/dco_{video_id}.mp4")
        if tmp_path.exists():
            self.logger.debug(f"Vidéo déjà en cache : {video_id}")
            return tmp_path

        url = f"https://www.youtube.com/watch?v={video_id}"
        cmd = [
            "yt-dlp",
            "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]",
            "--merge-output-format", "mp4",
            "-o", str(tmp_path),
            url,
        ]
        self.logger.info(f"  Téléchargement : {url}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            self.logger.error(f"  yt-dlp échoué : {result.stderr[:300]}")
            return None
        return tmp_path

    def cut_clip(
        self,
        source: Path,
        start: float,
        end: float,
        output_path: Path,
        transcript: Optional[list[dict]] = None,
    ) -> bool:
        """Découpe un segment, reformate en Shorts 9:16 et incruste les sous-titres."""
        import tempfile, shutil as _shutil
        out_cfg = self.clip_cfg["output"]
        duration = end - start

        # Générer le fichier ASS de sous-titres si transcript disponible
        ass_path = None
        if transcript:
            try:
                ass_content = self._build_ass_subtitles(transcript, start, end)
                tmp_ass = tempfile.NamedTemporaryFile(
                    suffix=".ass", delete=False, mode="w", encoding="utf-8"
                )
                tmp_ass.write(ass_content)
                tmp_ass.close()
                ass_path = tmp_ass.name
            except Exception as e:
                self.logger.warning(f"  Sous-titres ignorés : {e}")
                ass_path = None

        # Filtre vidéo : recadrage + sous-titres incrustés
        if ass_path:
            # Sur Windows, ffmpeg veut les backslashes échappés dans le filtre
            ass_escaped = ass_path.replace("\\", "/").replace(":", "\\:")
            vf = (
                f"scale=1080:1920:force_original_aspect_ratio=increase,"
                f"crop=1080:1920,"
                f"subtitles='{ass_escaped}'"
            )
        else:
            vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"

        cmd = [
            "ffmpeg", "-y",
            "-ss", str(start),
            "-i", str(source),
            "-t", str(duration),
            "-vf", vf,
            "-r", str(out_cfg["fps"]),
            "-c:v", out_cfg["video_codec"],
            "-crf", str(out_cfg["crf"]),
            "-c:a", out_cfg["audio_codec"],
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Nettoyage du fichier ASS temporaire
        if ass_path:
            Path(ass_path).unlink(missing_ok=True)

        if result.returncode != 0:
            self.logger.error(f"  ffmpeg échoué : {result.stderr[-400:]}")
            return False
        self.logger.info(f"  Clip généré avec sous-titres : {output_path.name}")
        return True

    @staticmethod
    def _build_ass_subtitles(
        transcript: list[dict], clip_start: float, clip_end: float
    ) -> str:
        """
        Génère un fichier ASS avec des sous-titres style TikTok/Shorts :
        texte blanc centré, grande police, contour noir épais.
        Les timestamps sont relatifs au début du clip.
        """
        def sec_to_ass(seconds: float) -> str:
            seconds = max(0.0, seconds)
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = seconds % 60
            return f"{h}:{m:02d}:{s:05.2f}"

        # Style TikTok : gros texte blanc, contour noir, centré bas-milieu
        header = """\
[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 1

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,72,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,2,0,1,5,2,2,60,60,350,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
        lines = []
        # Filtrer et regrouper les segments du clip
        clip_segments = [
            s for s in transcript
            if s["start"] < clip_end and (s["start"] + s.get("duration", 2)) > clip_start
        ]

        # Regrouper en blocs de ~8 mots max pour l'effet phrase par phrase
        def group_segments(segs, max_words=8):
            groups = []
            current_text = []
            current_start = None
            current_end = None
            word_count = 0

            for seg in segs:
                words = seg["text"].split()
                if current_start is None:
                    current_start = seg["start"]

                current_text.extend(words)
                current_end = seg["start"] + seg.get("duration", 2)
                word_count += len(words)

                if word_count >= max_words:
                    groups.append({
                        "text": " ".join(current_text),
                        "start": current_start,
                        "end": current_end,
                    })
                    current_text = []
                    current_start = None
                    word_count = 0

            if current_text and current_start is not None:
                groups.append({
                    "text": " ".join(current_text),
                    "start": current_start,
                    "end": current_end,
                })
            return groups

        groups = group_segments(clip_segments)
        for grp in groups:
            # Temps relatif au début du clip
            t_start = max(0.0, grp["start"] - clip_start)
            t_end = min(clip_end - clip_start, grp["end"] - clip_start)
            if t_end <= t_start:
                continue
            text = grp["text"].strip().upper()  # MAJUSCULES style TikTok
            lines.append(
                f"Dialogue: 0,{sec_to_ass(t_start)},{sec_to_ass(t_end)},"
                f"Default,,0,0,0,,{text}"
            )

        return header + "\n".join(lines) + "\n"

    def build_output_path(
        self,
        theme_id: str,
        video_id: str,
        clip_index: int,
    ) -> Path:
        date_str = datetime.now().strftime("%Y%m%d")
        template = self.storage_cfg["filename_template"]
        filename = template.format(
            theme_id=theme_id,
            video_id=video_id,
            clip_index=clip_index,
            date=date_str,
        ) + ".mp4"
        return self.output_dir / filename

    def cleanup_source(self, source: Path):
        if not self.storage_cfg.get("keep_source_video", False):
            source.unlink(missing_ok=True)
            self.logger.debug(f"Source supprimée : {source.name}")


# ─────────────────────────────────────────────────────────────
# UPLOAD YOUTUBE SHORTS
# ─────────────────────────────────────────────────────────────

class YouTubeUploader:
    """
    Publie les clips générés directement sur la chaîne YouTube D&Co
    en utilisant les credentials OAuth existants (scope youtube.upload).
    """

    HASHTAGS = ["#Shorts", "#TransformationIA", "#IA", "#PME", "#Leadership"]
    CATEGORY_ID = "28"   # Science & Technology

    def __init__(self, config: dict, logger: logging.Logger):
        self.cfg = config
        self.logger = logger
        self.service = self._build_service()
        self.enabled = self.service is not None

    def _build_service(self):
        """Construit le service YouTube avec les credentials OAuth."""
        client_id     = os.environ.get("YOUTUBE_CLIENT_ID")
        client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET")
        refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN")

        if not all([client_id, client_secret, refresh_token]):
            self.logger and self.logger.warning(
                "  Upload YouTube désactivé — YOUTUBE_CLIENT_ID / "
                "YOUTUBE_CLIENT_SECRET / YOUTUBE_REFRESH_TOKEN manquants"
            )
            return None

        try:
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build as yt_build

            creds = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
            )
            return yt_build("youtube", "v3", credentials=creds)
        except Exception as e:
            self.logger.error(f"  Erreur init upload YouTube : {e}")
            return None

    def upload_clip(self, clip_meta: dict) -> Optional[str]:
        """
        Upload un clip MP4 comme YouTube Short.
        Retourne l'URL de la vidéo uploadée ou None en cas d'échec.
        """
        if not self.enabled:
            return None

        clip_path = Path(clip_meta["clip_file"])
        if not clip_path.exists():
            self.logger.error(f"  Fichier clip introuvable : {clip_path}")
            return None

        # Titre : caption IA + #Shorts (obligatoire pour être reconnu comme Short)
        caption = clip_meta.get("caption", clip_meta.get("video_title", ""))[:80]
        title = f"{caption} #Shorts"[:100]

        # Description : contexte + source + hashtags
        hashtags_str = " ".join(self.HASHTAGS)
        description = (
            f"{clip_meta.get('reason', '')}\n\n"
            f"Extrait de : {clip_meta['video_title']}\n"
            f"Source : {clip_meta['video_url']}\n\n"
            f"Thème : {clip_meta['theme_label']}\n\n"
            f"{hashtags_str}"
        )

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": [t.lstrip("#") for t in self.HASHTAGS] + [clip_meta["theme_id"]],
                "categoryId": self.CATEGORY_ID,
                "defaultLanguage": "fr",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "madeForKids": False,
            },
        }

        try:
            from googleapiclient.http import MediaFileUpload

            media = MediaFileUpload(
                str(clip_path),
                mimetype="video/mp4",
                resumable=True,
                chunksize=5 * 1024 * 1024,  # 5 MB chunks
            )
            self.logger.info(f"  Upload YouTube : {clip_path.name}")
            request = self.service.videos().insert(
                part=",".join(body.keys()),
                body=body,
                media_body=media,
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    self.logger.info(f"    Upload progression : {pct}%")

            video_id = response["id"]
            url = f"https://www.youtube.com/shorts/{video_id}"
            self.logger.info(f"  ✅ Short publié : {url}")
            return url

        except Exception as e:
            self.logger.error(f"  ❌ Erreur upload YouTube : {e}")
            return None


# ─────────────────────────────────────────────────────────────
# MÉTADONNÉES & DÉDUPLICATION
# ─────────────────────────────────────────────────────────────

class MetadataStore:
    def __init__(self, config: dict):
        self.meta_dir = Path(config["storage"]["metadata_dir"])
        self.meta_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.meta_dir / "clips_index.json"
        self.index = self._load_index()

    def _load_index(self) -> dict:
        if self.index_file.exists():
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"processed_videos": [], "clips": []}

    def save(self):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)

    def is_processed(self, video_id: str) -> bool:
        return video_id in self.index["processed_videos"]

    def mark_processed(self, video_id: str):
        if video_id not in self.index["processed_videos"]:
            self.index["processed_videos"].append(video_id)

    def add_clip(self, clip_meta: dict):
        self.index["clips"].append(clip_meta)

    # ── Uploads en attente (limite quotidienne YouTube) ──────────

    def add_pending_upload(self, clip_meta: dict):
        """Sauvegarde un clip dont l'upload a échoué pour re-tentative ultérieure."""
        pending = self._load_pending()
        # Éviter les doublons
        if not any(p["clip_file"] == clip_meta["clip_file"] for p in pending):
            pending.append(clip_meta)
            self._save_pending(pending)

    def remove_pending_upload(self, clip_file: str):
        """Retire un clip de la liste pending après upload réussi."""
        pending = self._load_pending()
        pending = [p for p in pending if p["clip_file"] != clip_file]
        self._save_pending(pending)

    def get_pending_uploads(self) -> list[dict]:
        return self._load_pending()

    def _pending_file(self) -> Path:
        return self.meta_dir / "pending_uploads.json"

    def _load_pending(self) -> list[dict]:
        f = self._pending_file()
        if f.exists():
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        return []

    def _save_pending(self, pending: list[dict]):
        with open(self._pending_file(), "w", encoding="utf-8") as fh:
            json.dump(pending, fh, ensure_ascii=False, indent=2)

    def get_clip_count_today(self) -> int:
        today = datetime.now().strftime("%Y%m%d")
        return sum(
            1 for c in self.index["clips"]
            if c.get("created_at", "").startswith(today)
        )


# ─────────────────────────────────────────────────────────────
# ORCHESTRATEUR PRINCIPAL
# ─────────────────────────────────────────────────────────────

class ClippingEngine:
    def __init__(self, config: dict):
        self.config = config
        self.logger = setup_logging(config)
        self.searcher = YouTubeSearcher(
            config=config,
            logger=self.logger,
        )
        self.transcriber = Transcriber(config, self.logger)
        self.ai_selector = AISelector(config, self.logger)
        self.processor = VideoProcessor(config, self.logger)
        self.metadata = MetadataStore(config)
        self.uploader = YouTubeUploader(config, self.logger)

    def run(
        self,
        theme_filter: Optional[str] = None,
        max_clips_override: Optional[int] = None,
        language_override: Optional[str] = None,
    ):
        themes = self.config["themes"]
        if theme_filter:
            themes = [t for t in themes if t["id"] == theme_filter]
            if not themes:
                self.logger.error(f"Thème introuvable : {theme_filter}")
                return

        max_total = max_clips_override or self.config["clipping"]["max_clips_per_run"]
        clips_generated = 0
        all_clips_meta = []

        self.logger.info(f"=== D&Co Clipping Engine démarré — {len(themes)} thème(s) ===")

        # Re-tenter les uploads en attente du run précédent
        self._retry_pending_uploads()

        for theme in sorted(themes, key=lambda t: t.get("priority", "medium") != "high"):
            if clips_generated >= max_total:
                break

            self.logger.info(f"\n── Thème : {theme['label']} ──")

            for keyword in theme["keywords"]:
                if clips_generated >= max_total:
                    break

                lang = language_override or theme.get("language", "fr")
                videos = self.searcher.search_videos(keyword, lang)

                for video in videos:
                    if clips_generated >= max_total:
                        break
                    if self.metadata.is_processed(video["video_id"]):
                        self.logger.debug(f"Déjà traité : {video['video_id']}")
                        continue

                    remaining = max_total - clips_generated
                    clips_meta = self._process_video(video, theme, max_clips_override=min(3, remaining))
                    clips_generated += len(clips_meta)
                    all_clips_meta.extend(clips_meta)
                    # Marquer traité UNIQUEMENT si des clips ont été générés
                    # → les vidéos sans transcript ou sous le seuil seront retentées
                    if clips_meta:
                        self.metadata.mark_processed(video["video_id"])
                        self.metadata.save()

        self.logger.info(
            f"\n=== Terminé : {clips_generated} clip(s) généré(s) ==="
        )
        self._print_summary(all_clips_meta)

    def _process_video(
        self, video: dict, theme: dict, max_clips_override: int = 3
    ) -> list[dict]:
        video_id = video["video_id"]
        self.logger.info(f"\nTraitement : {video['title'][:70]}")
        self.logger.info(f"  URL : {video['url']}")

        # 1. Transcription
        transcript = self.transcriber.get_transcript(video_id)
        if not transcript:
            self.logger.warning("  Pas de transcription disponible — vidéo ignorée")
            return []

        # 2. Sélection IA des meilleurs moments
        clip_moments = self.ai_selector.select_best_moments(
            transcript=transcript,
            video_meta=video,
            theme=theme,
            max_clips=min(max_clips_override, self.config["clipping"]["max_clips_per_video"]),
        )
        if not clip_moments:
            self.logger.info("  Aucun moment retenu par Claude")
            return []

        # 3. Téléchargement de la vidéo source
        source_path = self.processor.download_video(video_id)
        if not source_path:
            return []

        # 4. Découpe et export des clips
        clips_meta = []
        for i, moment in enumerate(clip_moments, start=1):
            output_path = self.processor.build_output_path(
                theme["id"], video_id, i
            )
            # Ajustement intelligent des points de coupe
            raw_start = float(moment["start"])
            raw_end   = float(moment["end"])
            smart_start, smart_end = self._smart_cut_points(
                transcript, raw_start, raw_end
            )
            self.logger.info(
                f"  Coupe ajustée : {raw_start:.1f}→{smart_start:.1f}s "
                f"/ {raw_end:.1f}→{smart_end:.1f}s "
                f"(durée {smart_end - smart_start:.1f}s)"
            )
            success = self.processor.cut_clip(
                source=source_path,
                start=smart_start,
                end=smart_end,
                output_path=output_path,
                transcript=transcript,
            )
            if success:
                meta = {
                    "clip_file": str(output_path),
                    "video_id": video_id,
                    "video_title": video["title"],
                    "channel": video["channel"],
                    "video_url": video["url"],
                    "theme_id": theme["id"],
                    "theme_label": theme["label"],
                    "start": smart_start,
                    "end": smart_end,
                    "duration": round(smart_end - smart_start, 1),
                    "score": moment.get("score", 0),
                    "reason": moment.get("reason", ""),
                    "caption": moment.get("caption", ""),
                    "created_at": datetime.now().isoformat(),
                }
                self.metadata.add_clip(meta)
                clips_meta.append(meta)

        # 5. Upload YouTube Shorts
        for meta in clips_meta:
            youtube_url = self.uploader.upload_clip(meta)
            if youtube_url:
                meta["youtube_url"] = youtube_url
            elif self.uploader.enabled:
                # Upload échoué (limite quotidienne, quota API…) → file d'attente
                self.metadata.add_pending_upload(meta)
                self.logger.warning(
                    f"  ⏳ Upload différé : {Path(meta['clip_file']).name} "
                    f"(ajouté à pending_uploads.json)"
                )

        # 6. Nettoyage source
        self.processor.cleanup_source(source_path)
        return clips_meta

    def _smart_cut_points(
        self,
        transcript: list[dict],
        start: float,
        end: float,
        window: float = 6.0,
    ) -> tuple[float, float]:
        """
        Ajuste start/end pour couper sur des frontières naturelles
        (fin de phrase, fin de citation, fin de sujet) détectées dans le transcript.
        Cherche dans une fenêtre de ±window secondes autour de chaque point.
        Respecte les contraintes de durée min/max de la config.
        """
        dur_min = self.config["clipping"]["clip_duration_min"]
        dur_max = self.config["clipping"]["clip_duration_max"]

        SENTENCE_END = re.compile(r'[.!?…»""\']\s*$')

        def seg_end(seg: dict) -> float:
            return seg["start"] + seg.get("duration", 2.0)

        # ── Point de début : trouver le début de segment le plus proche ──
        start_candidates = [
            seg for seg in transcript
            if abs(seg["start"] - start) <= window
        ]
        if start_candidates:
            best_start_seg = min(
                start_candidates,
                key=lambda s: abs(s["start"] - start)
            )
            new_start = best_start_seg["start"]
        else:
            new_start = start

        # ── Point de fin : préférer une fin de phrase dans la fenêtre ──
        end_candidates = [
            seg for seg in transcript
            if abs(seg_end(seg) - end) <= window
        ]
        # D'abord essayer ceux qui terminent sur de la ponctuation forte
        good_end = [s for s in end_candidates if SENTENCE_END.search(s["text"])]
        pool = good_end if good_end else end_candidates

        if pool:
            best_end_seg = min(pool, key=lambda s: abs(seg_end(s) - end))
            new_end = seg_end(best_end_seg)
        else:
            new_end = end

        # ── Garantir le respect des durées min/max ──
        duration = new_end - new_start
        if duration < dur_min:
            new_end = new_start + dur_min
        elif duration > dur_max:
            new_end = new_start + dur_max

        return round(new_start, 2), round(new_end, 2)

    def _retry_pending_uploads(self):
        """Re-tente l'upload des clips mis en attente lors d'un run précédent."""
        pending = self.metadata.get_pending_uploads()
        if not pending:
            return

        self.logger.info(f"\n── Re-tentative de {len(pending)} upload(s) en attente ──")
        for meta in list(pending):
            clip_path = Path(meta["clip_file"])
            if not clip_path.exists():
                self.logger.warning(
                    f"  Fichier introuvable, supprimé de la file : {clip_path.name}"
                )
                self.metadata.remove_pending_upload(meta["clip_file"])
                continue

            youtube_url = self.uploader.upload_clip(meta)
            if youtube_url:
                meta["youtube_url"] = youtube_url
                self.metadata.remove_pending_upload(meta["clip_file"])
                self.logger.info(f"  ✅ Upload différé réussi : {youtube_url}")
            else:
                self.logger.warning(
                    f"  ❌ Upload toujours impossible : {clip_path.name} — conservé en file d'attente"
                )

    def _print_summary(self, clips: list[dict]):
        if not clips:
            return
        self.logger.info("\n─── RÉCAPITULATIF DES CLIPS GÉNÉRÉS ───")
        for c in clips:
            self.logger.info(
                f"  [{c['theme_id']}] {Path(c['clip_file']).name} "
                f"| {c['duration']}s | score={c['score']:.2f}"
            )
            self.logger.info(f"    Source : {c['video_title'][:60]}")
            self.logger.info(f"    Caption : {c['caption'][:100]}")
            if c.get("youtube_url"):
                self.logger.info(f"    YouTube : {c['youtube_url']}")


# ─────────────────────────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="D&Co Clipping Engine — génère des clips YouTube Shorts"
    )
    parser.add_argument(
        "--config", default="clipping_config.yaml",
        help="Chemin vers le fichier YAML de configuration"
    )
    parser.add_argument(
        "--theme", default=None,
        help="Filtrer sur un thème précis (ex: transformation_ia)"
    )
    parser.add_argument(
        "--max-clips", type=int, default=None,
        help="Nombre maximum de clips à générer (override config)"
    )
    parser.add_argument(
        "--language", default=None,
        help="Langue de recherche : 'fr' (francophone), 'en' (anglophone), etc. "
             "Surcharge la langue définie par thème."
    )
    parser.add_argument(
        "--list-themes", action="store_true",
        help="Lister les thèmes disponibles et quitter"
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)

    if args.list_themes:
        print("\nThèmes disponibles :")
        for t in config["themes"]:
            print(f"  {t['id']:30s} | {t['label']}")
        return

    # Vérification des variables d'environnement requises
    required_env = ["YOUTUBE_API_KEY", "ANTHROPIC_API_KEY"]
    missing = [v for v in required_env if not os.environ.get(v)]
    if missing:
        print(f"Erreur : variables d'environnement manquantes : {', '.join(missing)}")
        sys.exit(1)

    engine = ClippingEngine(config)
    engine.run(
        theme_filter=args.theme,
        max_clips_override=args.max_clips,
        language_override=args.language,
    )


if __name__ == "__main__":
    main()
