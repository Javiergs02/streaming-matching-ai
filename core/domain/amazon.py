from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from core.normalization.title import normalize_title

AMAZON_USD_TO_EUR = 0.92
AMAZON_EUR_TO_USD = 1.0 / AMAZON_USD_TO_EUR


def convert_amazon_eur_to_usd(amount_eur: float | None, currency: str | None = None) -> float:
    """Converts Amazon royalties to USD for dashboard parity.

    If currency is explicitly 'USD', returns the amount as-is.
    If currency is 'EUR' or unspecified (legacy MongoDB records), converts using 1.0 / 0.92.
    """
    if amount_eur is None:
        return 0.0
    val = float(amount_eur)
    if currency and currency.strip().upper() == "USD":
        return round(val, 6)
    return round(val * AMAZON_EUR_TO_USD, 6)


@dataclass(frozen=True)
class AmazonPerformanceRecord:
    date: date
    title_id: str
    title_name: str
    season_id: str
    season_name: str
    series_id: str
    series_name: str
    offer_type: str
    region: str
    territory: str
    minutes_streamed: float
    unique_streams: int
    is_movie: bool


def load_amazon_match_scores(mappings_path: str | Path | None = None) -> dict[str, float]:
    """Carga los porcentajes de acierto/confianza del matching de IA desde production_mappings.csv.

    Exact matches se normalizan al 100.0%.
    Semantic AI matches utilizan la puntuación de similitud semántica (0.0 - 100.0%).
    Unmatched o descartados devuelven 0.0%.
    """
    if mappings_path is None:
        root = Path(__file__).resolve().parent.parent.parent
        mappings_path = root / "data" / "output" / "production_mappings.csv"
    else:
        mappings_path = Path(mappings_path)

    if not mappings_path.exists():
        return {}

    score_map: dict[str, float] = {}
    with open(mappings_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            orig = (row.get("Amazon Original Title") or "").strip()
            if not orig:
                continue

            method = (row.get("Match Method") or "").strip()
            score_str = (row.get("Score") or "").strip()
            status = (row.get("Match Status") or "").strip().upper()

            if status == "UNMATCHED" or method in (
                "blacklist",
                "alien_series_rejected",
                "alien_series_blacklist",
                "unmatched_constrained_no_candidate",
                "unmatched_special",
                "movie",
            ):
                val = 0.0
            elif method == "exact_title" or score_str == "1.0":
                val = 100.0
            else:
                try:
                    val = float(score_str)
                    if 0.0 < val <= 1.0:
                        val = val * 100.0
                except (ValueError, TypeError):
                    val = 100.0 if status == "MATCH" else 0.0

            score_val = round(min(100.0, max(0.0, val)), 1)
            score_map[orig] = score_val
            norm = normalize_title(orig)
            if norm not in score_map:
                score_map[norm] = score_val

    return score_map


def get_title_match_score(
    title: str | None,
    is_unmatched: bool = False,
    score_map: dict[str, float] | None = None,
) -> float:
    """Devuelve el porcentaje de acierto del match para un título de Amazon."""
    if is_unmatched or not title:
        return 0.0
    t_str = str(title).strip()
    if t_str.startswith("UNMATCHED") or t_str in ("Unknown Title", "Unknown Amazon Title"):
        return 0.0
    if not score_map:
        return 100.0
    if t_str in score_map:
        return score_map[t_str]
    norm = normalize_title(t_str)
    if norm in score_map:
        return score_map[norm]
    return 100.0


def load_amazon_broadkast_titles(mappings_path: str | Path | None = None) -> dict[str, str]:
    """Carga los títulos de producción asignados de Broadkast desde production_mappings.csv.

    Mapea tanto por Broadkast ID (ej. 'EP_2606' -> 'Mud Trap')
    como por título original en Amazon (ej. 'Mud Trap / The Cold' -> 'Mud Trap').
    Descarta títulos genéricos con formato de fallback '... - Ep \\d+'.
    """
    if mappings_path is None:
        root = Path(__file__).resolve().parent.parent.parent
        mappings_path = root / "data" / "output" / "production_mappings.csv"
    else:
        mappings_path = Path(mappings_path)

    if not mappings_path.exists():
        return {}

    title_map: dict[str, str] = {}
    import re

    with open(mappings_path, mode="r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            bkid = (row.get("Broadkast ID") or "").strip()
            btitle = (row.get("Broadkast Assigned Title") or "").strip()
            orig = (row.get("Amazon Original Title") or "").strip()
            status = (row.get("Match Status") or "").strip().upper()

            if not btitle or bkid == "UNMATCHED" or status == "UNMATCHED":
                continue
            if re.search(r" - Ep \d+$", btitle):
                continue

            if bkid and bkid not in title_map:
                title_map[bkid] = btitle

            if orig and orig not in title_map:
                title_map[orig] = btitle

            norm_orig = normalize_title(orig)
            if norm_orig and norm_orig not in title_map:
                title_map[norm_orig] = btitle

    return title_map


def get_broadkast_title(
    bkid: str | None = None,
    amazon_title: str | None = None,
    default: str | None = None,
    title_map: dict[str, str] | None = None,
) -> str:
    """Obtiene el título de producción de Broadkast correspondiente a un ID o título de Amazon."""
    if not title_map:
        return default or (amazon_title or "")
    if bkid and str(bkid).strip() in title_map:
        return title_map[str(bkid).strip()]
    if amazon_title:
        t_str = str(amazon_title).strip()
        if t_str in title_map:
            return title_map[t_str]
        norm = normalize_title(t_str)
        if norm in title_map:
            return title_map[norm]
    return default or (amazon_title or "")


def load_broadkast_english_titles(cache_path: str | Path | None = None) -> dict[str, list[str]]:
    """Carga el diccionario de títulos canónicos en inglés de Broadkast por Broadkast ID (ej. 'EP_2684' -> ["Trackodile's Toothache"])."""
    if cache_path is None:
        root = Path(__file__).resolve().parent.parent.parent
        cache_path = root / "data" / "cache" / "broadkast_canonical_english_titles.json"
    else:
        cache_path = Path(cache_path)

    if cache_path.exists():
        try:
            with open(cache_path, mode="r", encoding="utf-8") as f:
                data = json.load(f)
                res: dict[str, list[str]] = {}
                for k, v in data.items():
                    if isinstance(v, list):
                        res[k] = v
                    elif isinstance(v, str):
                        res[k] = [v]
                return res
        except Exception:
            pass
    return {}


_LATIN_ACCENTS = "áàâãäåéèêëíìîïóòôõöøúùûüñçýÿąćęłńśźżÁÀÂÃÄÅÉÈÊËÍÌÎÏÓÒÔÕÖØÚÙÛÜÑÇÝĄĆĘŁŃŚŹŻ"
_LATIN_REPLACEMENTS = "aaaaaaeeeeiiiioooooouuuuncyyacelnszzAAAAAAEEEEIIIIOOOOOOUUUUNCYACELNSZZ"
_ACCENT_TRANS = str.maketrans(_LATIN_ACCENTS, _LATIN_REPLACEMENTS)


def _strip_accents(s: str) -> str:
    """Elimina acentos y diacríticos latinos preservando scripts no latinos (CJK, tailandés, cirílico)."""
    return s.replace("ß", "ss").translate(_ACCENT_TRANS)


MULTILINGUAL_COGNATES: dict[str, list[str]] = {
    "garden": ["jardin", "giardin", "gärtn", "gaertn", "ガーデン", "ガーデニング", "花园", "园艺", "สวน"],
    "turtle": ["tortug", "tartarug", "tortue", "schildkröt", "schildkroet", "カメ", "乌龟", "เต่า"],
    "trucktle": ["tortug", "tartarug", "tortue", "schildkröt", "schildkroet", "カメ", "乌龟", "เต่า"],
    "truck": ["camion", "caminh", "lastwagen", "laster", "トラック", "卡车", "รถบรรทุก"],
    "firetruck": ["bomber", "feuerwehr", "pompier", "消防", "รถดับเพลิง"],
    "learn": ["aprend", "impar", "lern", "apprend", "学", "学ぶ", "เรียน"],
    "lizard": ["lagart", "lucertol", "lézard", "lezard", "eidechs", "トカゲ", "蜥蜴"],
    "bath": ["bañ", "banh", "bain", "bad", "風呂", "洗澡", "อาบน้ำ"],
    "teeth": ["dient", "dent", "zahn", "zähn", "zaehn", "歯", "牙"],
    "tooth": ["dient", "dent", "zahn", "zähn", "zaehn", "歯", "牙"],
    "toothache": ["mal di denti", "dolor de muelas", "zahnschmerzen", "mal de dents", "牙痛", "歯痛"],
    "crocodile": ["coccodril", "cocodril", "crocodil", "krokodil", "krokodyl", "ワニ", "鳄鱼", "จระเข้"],
    "trackodile": ["coccodril", "cocodril", "crocodil", "krokodil", "krokodyl", "ワニ", "鳄鱼", "จระเข้"],
    "sweet": ["dulce", "doce", "doux", "süß", "suess", "甘", "甜"],
    "sandcastle": ["castillo", "castelo", "château", "chateau", "burg", "砂の城", "沙堡", "ปราสาททราย"],
    "fly": ["mosca", "mouche", "flieg", "ハエ", "苍蝇", "แมลงวัน"],
    "trap": ["tramp", "pièg", "pieg", "fall", "罠", "陷阱", "กับดัก"],
    "spider": ["arañ", "aranh", "aragn", "spinn", "クモ", "蜘蛛", "แมงมุม"],
    "train": ["tren", "trem", "zug", "treno", "列车", "列車", "火车", "รถไฟ"],
    "fire": ["fuego", "fogo", "feu", "feuer", "fuoco", "火", "เพลิง", "ไฟ"],
    "water": ["agua", "água", "eau", "wasser", "acqua", "水", "น้ำ"],
    "dinosaur": ["dinosau", "dinozau", "恐竜", "恐龙", "ไดโนเสาร์"],
    "ghost": ["fantas", "fantôm", "fantome", "gespenst", "幽霊", "鬼", "ผี"],
    "police": ["polic", "poliz", "警察", "パトカー", "警车", "ตำรวจ"],
    "ambulance": ["ambulan", "krankenwagen", "救急車", "救护车", "รถพยาบาล"],
    "doctor": ["médic", "medic", "medico", "docteur", "arzt", "医者", "医生", "หมอ"],
    "flower": ["flor", "fleur", "blume", "fiore", "kwiat", "花", "ดอกไม้"],
    "cake": ["pastel", "bolo", "gâteau", "gateau", "kuchen", "torta", "ciasto", "ケーキ", "蛋糕", "เค้ก"],
    "christmas": ["navidad", "natal", "noël", "noel", "weihnacht", "クリスマス", "圣诞", "คริสต์มาส"],
    "halloween": ["halloween", "bruxa", "ハロウィン", "万圣节", "ฮาโลวีน"],
    "easter": ["pascua", "páscoa", "pâques", "paques", "ostern", "イースター", "复活节", "อีสเตอร์"],
    "egg": ["huevo", "ovo", "oeuf", "ei", "jaj", "卵", "蛋", "ไข่"],
    "ball": ["pelota", "bola", "balle", "ball", "palla", "piłka", "pilka", "ボール", "球", "ลูกบอล"],
    "race": ["carrera", "corrida", "course", "rennen", "corsa", "wyścig", "wyscig", "レース", "赛车", "แข่ง"],
    "car": ["coche", "auto", "carro", "voiture", "wagen", "samochód", "samochod", "車", "车", "รถ"],
    "rescue": ["rescate", "resgate", "sauvetage", "rettung", "soccorso", "ratunek", "救助", "レスキュー", "救援", "กู้ภัย", "ช่วยเหลือ"],
    "tow": ["remolc", "depann", "abschlepp", "rimorch", "holow", "レッカー", "拖车", "ลาก"],
    "shark": ["tiburon", "tubarao", "requin", "hai", "squalo", "rekin", "サメ", "鲨鱼", "ฉลาม"],
    "hide": ["escond", "versteck", "cache-cache", "nascond", "chowany", "かくれんぼ", "捉迷藏", "ซ่อน"],
    "valentine": ["walentynk", "valentin", "バレンタイン", "情人节"],
    "beach": ["playa", "praia", "plage", "strand", "spiagg", "plaz", "砂浜", "海滩", "หาด"],
    "ice": ["hielo", "gelo", "glace", "eis", "ghiaccio", "lód", "lod", "氷", "冰", "น้ำแข็ง"],
    "snow": ["nieve", "neve", "neige", "schnee", "śnieg", "snieg", "雪", "หิมะ"],
    "sleep": ["dorm", "schlaf", "sommeil", "sonno", "sen", "眠", "睡", "นอน"],
    "balloon": ["globo", "balão", "ballon", "pallonc", "balon", "風船", "气球", "ลูกโป่ง"],
    "magic": ["mágic", "magic", "magi", "zauber", "魔", "魔法", "มายากล"],
    "color": ["color", "cor", "couleur", "farbe", "kolor", "色", "颜色", "สี"],
    "shape": ["forma", "forme", "form", "kształt", "ksztalt", "形", "形状", "รูปร่าง"],
    "baby": ["bebé", "bebe", "bébé", "baby", "bambin", "niemowlę", "赤ちゃん", "宝宝", "ทารก"],
    "super": ["súper", "super", "superhero", "スーパー", "超级", "ซูเปอร์"],
    "firework": ["fuegos artificiales", "fogos", "feuerwerk", "feu d'artifice", "fuochi", "fajerwerki", "花火", "烟花", "พลุ"],
    "crane": ["grúa", "grua", "grue", "kran", "gru", "dźwig", "クレーン", "起重机", "เครน"],
    "bulldozer": ["excavadora", "buldózer", "bulldozer", "planier", "ブルドーザー", "推土机"],
    "pool": ["piscina", "piscine", "swimming", "becken", "basen", "プール", "游泳池", "สระว่ายน้ำ"],
    "monster": ["monstru", "monstr", "ungeheuer", "monstro", "potwór", "怪物", "怪兽"],
    "song": ["canción", "cancion", "canção", "cancao", "chanson", "lied", "canzone", "piosenk", "歌", "歌曲", "เพลง"],
}


def get_best_english_title(
    bkid: str | None,
    match_title: str | None = None,
    amazon_title: str | None = None,
    en_map: dict[str, list[str] | str] | None = None,
    default: str | None = None,
) -> str:
    """Selecciona el título canónico en inglés más preciso para un episodio, resolviendo ambigüedades en episodios dobles."""
    if not bkid or not en_map or bkid not in en_map:
        return default or (match_title or (amazon_title or ""))

    raw_val = en_map[bkid]
    candidates: list[str] = raw_val if isinstance(raw_val, list) else [raw_val]
    if not candidates:
        return default or (match_title or (amazon_title or ""))
    if len(candidates) == 1:
        return candidates[0]

    m_clean = (match_title or "").strip()
    if m_clean:
        for c in candidates:
            if c.lower() == m_clean.lower():
                return c

    import re
    from difflib import SequenceMatcher

    amz_raw = (amazon_title or "").lower()
    m_raw = m_clean.lower()
    amz_norm = _strip_accents(amz_raw)
    m_norm = _strip_accents(m_raw)

    def _score(cand: str) -> float:
        cand_lower = cand.lower()
        cand_norm = _strip_accents(cand_lower)
        c_words = [w for w in re.findall(r"\w+", cand_norm) if len(w) >= 3]
        if not c_words:
            return 0.0
        points = 0.0
        for w in c_words:
            if w in amz_norm:
                points += len(w) * 2.0
            elif len(w) >= 4 and w[:4] in amz_norm:
                points += 4.0
            if w in m_norm:
                points += len(w) * 2.0
            elif len(w) >= 4 and w[:4] in m_norm:
                points += 4.0

        for concept, variants in MULTILINGUAL_COGNATES.items():
            if concept in cand_norm:
                for var in variants:
                    if var in amz_norm or var in amz_raw:
                        points += 25.0
                        break
                for var in variants:
                    if var in m_norm or var in m_raw:
                        points += 25.0
                        break

        if "|" in cand or "#" in cand:
            points -= 100.0
        points += SequenceMatcher(None, cand_norm, amz_norm).ratio()
        return points

    return max(candidates, key=_score)


def load_amazon_to_bkid_map(mappings_path: str | Path | None = None) -> dict[str, str]:
    """Mapea título de Amazon a su Broadkast ID (ej. 'Il mal di denti del coccodrillo' -> 'EP_2684')."""
    if mappings_path is None:
        root = Path(__file__).resolve().parent.parent.parent
        mappings_path = root / "data" / "output" / "production_mappings.csv"
    else:
        mappings_path = Path(mappings_path)

    if not mappings_path.exists():
        return {}

    bkid_map: dict[str, str] = {}
    with open(mappings_path, mode="r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            bkid = (row.get("Broadkast ID") or "").strip()
            orig = (row.get("Amazon Original Title") or "").strip()
            status = (row.get("Match Status") or "").strip().upper()
            if not bkid or bkid == "UNMATCHED" or status == "UNMATCHED":
                continue
            if orig and orig not in bkid_map:
                bkid_map[orig] = bkid
            norm = normalize_title(orig)
            if norm and norm not in bkid_map:
                bkid_map[norm] = bkid
    return bkid_map



