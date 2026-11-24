"""Multilingual series and franchise alias resolver for Amazon Prime Video.

Normalizes multilingual series names and title prefixes (in French, German, Italian,
Spanish, Portuguese, Japanese, Russian, Greek, Vietnamese, Turkish, Swedish, Polish,
Czech, Romanian, Estonian, Dutch, etc.) to canonical Broadkast series
and prevents cross-series / cross-franchise contamination.
"""

from __future__ import annotations

import re


def _try_decode_mojibake(text: str) -> list[str]:
    """Generates possible original strings by recovering common CP1252/Latin-1 mojibake encodings."""
    if not text or not isinstance(text, str):
        return []
    variants = [text]
    for enc in ("cp1252", "latin-1"):
        try:
            dec = text.encode(enc).decode("utf-8")
            if dec and dec not in variants:
                variants.append(dec)
        except Exception:
            pass
            
    # Robust mixed CP1252/Latin-1 character-by-character byte recovery
    cp1252_map = {
        '\u20ac': 0x80, '\u201a': 0x82, '\u0192': 0x83, '\u201e': 0x84,
        '\u2026': 0x85, '\u2020': 0x86, '\u2021': 0x87, '\u02c6': 0x88,
        '\u2030': 0x89, '\u0160': 0x8a, '\u2039': 0x8b, '\u0152': 0x8c,
        '\u017d': 0x8e, '\u2018': 0x91, '\u2019': 0x92, '\u201c': 0x93,
        '\u201d': 0x94, '\u2022': 0x95, '\u2013': 0x96, '\u2014': 0x97,
        '\u02dc': 0x98, '\u2122': 0x99, '\u0161': 0x9a, '\u203a': 0x9b,
        '\u0153': 0x9c, '\u017e': 0x9e, '\u0178': 0x9f
    }
    try:
        b = bytearray()
        for ch in text:
            if ch in cp1252_map:
                b.append(cp1252_map[ch])
            elif ord(ch) < 256:
                b.append(ord(ch))
            else:
                b = None
                break
        if b is not None:
            dec_robust = b.decode("utf-8", errors="ignore").strip()
            if dec_robust and dec_robust not in variants:
                variants.append(dec_robust)
    except Exception:
        pass
        
    return variants


# Alien series / Blacklist (multilingual: Millimages, Sunnyside, Toonbox, Shout! Factory, Shadow)
ALIEN_SERIES_PATTERNS = [
    r'(?i)(molang|моланг|モラン|ãƒ¢ãƒ©ãƒ³ã‚°)',
    r'(?i)(mouk|mokon\s*suuri\s*maailma|ムーク|ãƒ ãƒ¼ã‚¯)',
    r'(?i)(louie|didou|mal\s*mir|luluś|lulus|piirrä\s*minulle|tegn\s*meg)',
    r'(?i)(64\s*zoo\s*lane|zool[óo]gico\s*64|calle\s*del\s*zool|動物園通り64番地)',
    r'(?i)(diego\s*(&|et|y)\s*ziggy)',
    r'(?i)(kung\s*fu\s*bunny)',
    r'(?i)\bniko\b',
    r'(?i)(piccolo\s*,?\s*saxo)',
    r'(?i)(lascars)',
    r'(?i)(pirata\s*(&|et|y)?\s*capitano)',
    r'(?i)(jump\s*around)',
    r'(?i)(renaissance)',
    r'(?i)(kit\s*(\^n\^|n|and)\s*kate)',
    r'(?i)(groovy)',
    r'(?i)(superzoo)',
    r'(?i)(pipo)',
    r'(?i)(jasper|penguim\s*jasper|pinguino\s*jasper)',
    r'(?i)(cool\s*city)',
    r'(?i)(la\s*mouette\s*et\s*le\s*chat)',
    r'(?i)(chasseurs?\s*de\s*dragons?)',
    r'(?i)(cendrillon\s*au\s*far\s*west)',
]

# Thematic / Holiday / Generic seasonal / Educational prefixes before colon that are NOT series
THEMATIC_PREFIX_PATTERNS = [
    r'(?i)^(halloween(\s*special)?|dia\s*das\s*bruxas|ハロウィン)',
    r'(?i)^(christmas(\s*special)?|navidad|natale|natal|weihnachten|kerstmis|kerstmit|abriendo\s*regalos\s*de\s*navidad|クリスマス)',
    r'(?i)^(easter|pascua|pâques|ostern|pasen|dia\s*de\s*p[áa]scoa|giorno\s*di\s*pasqua|ziua\s*de\s*paste|wielkanoc|caça\s*ao\s*ovo|jajka|イースター)',
    r'(?i)^(summer(\s*safari)?|verano|ver[ãa]o|zomer|estate|sommer|夏)',
    r'(?i)^(winter|inverno|invierno|hiver|зима|冬)',
    r'(?i)^(spring|primavera|printemps|frühling|春)',
    r'(?i)^(thanksgiving|thanks\s*giving|acci[óo]n\s*de\s*gracias|a[çc][ãa]o\s*de\s*gra[çc]as|action\s*de\s*gr[âa]ce|muttertag|f[êe]te\s*des\s*m[èe]res|a[ñn]o\s*nuevo\s*chino|ano\s*novo\s*chin[êe]s|capodanno\s*cinese|chinesisches\s*neujahr|母の日|旧正月|大晦日)',
    r'(?i)^(april\s*fool|prima\s*aprilis|dia\s*dos\s*inocentes|d[íi]a\s*de\s*los\s*inocentes|pesce\s*d\'aprile|poisson\s*d\'avril|1\s*april)',
    r'(?i)^(back\s*to\s*school|vuelta\s*al\s*cole|volta\s*[àa]s\s*aulas|powr[óo]t\s*do\s*szko[łl]y|rentr[ée]e\s*scolaire)',
    r'(?i)^(learn\s*(colors|numbers|shapes|letters|the\s*alphabet)|aprende\s*los?\s*(colores|n[úu]meros|formas|el\s*alfabeto)|apprends?\s*(les\s*chiffres|les\s*couleurs|l\'alphabet)|impara\s*i\s*(colori|numeri|lettere)|lerne\s*(farben|zahlen|das\s*alphabet)|aprenda\s*(as\s*cores|os\s*n[úu]meros|o\s*alfabeto))',
    r'(?i)^(a\s*pescar|pesca|a\s*pesca|tiro\s*com\s*arco|tiro\s*al\s*arco|semana\s*do\s*tubar[ãa]o)',
]

# Canonical Series Rules (Ordered from most specific to generic fallback)
# Structure: (regex_pattern, canonical_series_name, canonical_project_name)
SERIES_RULES = [
    # INCREDITALES
    (r'(?i)(increditales|incredi\s*tales|インクレディテールズ|おとぎ話|m[äa]rchen\s*f[üu]r\s*kinder|fairy\s*tales\s*for\s*kids|ador[áa]vel\s*demais\s*para\s*assustar)', 'INCREDITALES_SKETCHES', 'INCREDITALES'),
    
    # COSMIC JAM
    (r'(?i)(cosmic\s*jam)', 'COSMIC_JAM', 'COSMIC_JAM'),
    
    # CAM & SAM
    (r'(?i)(cam\s*(&|and)\s*sam)', 'BABIES', 'BABIES'),
    
    # TRUCK GAMES
    (r'(?i)(truck\s*games)', 'BABY_TRUCKS', 'CARCITY_SUPER'),
    
    # ROBOFUSE (must be evaluated before general Tom/Car City)
    (r'(?i)(robofuse)', 'ROBOFUSE', 'CARCITY_SUPER'),
    
    # INVENTOM (must be evaluated before general Tom Tow Truck)
    (r'(?i)(inventom)', 'INVENTOM', 'CARCITY_SUPER'),
    
    # CREATIM (must be evaluated before general Tom Tow Truck)
    (r'(?i)(creatim)', 'CREATIM', 'CARCITY_SUPER'),
    
    # TOM'S PAINT SHOP (must be evaluated before Tom Tow Truck)
    (r'(?i)(paint\s*shop|peinture\s*de\s*tom|lackierwerkstatt|officina\s*di\s*verniciatura|oficina\s*de\s*pintura|taller\s*de\s*pintura|vopsitoria\s*lui\s*tom|autolakovna|lakiernia\s*toma|m[åa]larverkstad|малярная|ペイントショップ|βαφείο|tom.*boyac[ıi]|cửa\s*hàng\s*sơn\s*của\s*tom|cá».*hÃ.*sÆ.*tom|sanggar\s*lukis\s*tom|tom.*v[äa]rvikoda|tomova\s*lakirnica|ãƒˆãƒ ã.*ãƒšã‚¤ãƒ³ãƒˆ|ï„î¿\s*î²î±ï†îµî¯î¿|Ï„Î¿\s*Î²Î±Ï†|Ð¼Ð°Ð»Ñ)', 'TOM_PAINT_SHOP', 'CARCITY'),
    
    # TOM'S CAR WASH (must be evaluated before Tom Tow Truck)
    (r'(?i)(car\s*wash|lavage\s*auto|autowaschanlage|autolavaggio|lavado\s*de\s*autos|lavagem\s*de\s*carros|autowasstraat|spalatoria\s*auto|tomovo\s*um[ýy]v[áa]n[íi]|myjnia\s*samochodowa|автомойка|πλυντήριο|洗車場|æ´—è»Š|tom.*oto\s*y[ıi]kama|tiệm\s*rửa\s*xe\s*của\s*tom|tomi\s*autopesula|tomova\s*autopraonica|biltv[äa]tt|Î¤Î¿\s*Ï€Î»Ï…|Ð°Ð²Ñ‚Ð¾Ð¼Ð¾Ð¹ÐºÐ°)', 'TOMS_CAR_WASH', 'CARCITY'),
    
    # TOM'S GARAGE
    (r'(?i)(tom.*garage)', 'TOMS_GARAGE', 'CARCITY_SUPER'),
    
    # TOM THE TOW TRUCK
    (r'(?i)(tom.*tow\s*truck|tom.*d[ée]panneuse|tom.*abschleppwagen|tom.*carro\s*attrezzi|tom.*gr[úu]a|tom.*caminh[ãa]o.*reboque|tom.*takelwagen|tom.*camionul\s*de\s*tractari|tom.*odtahov|odtahov[ée]\s*auto\s*tom|tom\s*holownik|том\s*аварийка|эвакуатор\s*том|b[äa]rgningsbilen\s*tom|puksiirauto\s*tom|teglja[čc]\s*tom|tom.*truk\s*derek|xe\s*tải\s*kéo\s*tom|[çc]ekici\s*tom|ρυμουλκ|Î¤Î¿Î¼\s*Ï„Î¿\s*Î¡Ï…Î¼Î¿Ï…Î»ÎºÏŒ|Ð¢Ð¾Ð¼|Ñ\x8dÐ²Ð°ÐºÑƒÐ°Ñ‚Ð¾Ñ€|tom\s*die\s*tou\s*trok|レッカー車のトム|ãƒ¬ãƒƒã‚«ãƒ¼è»Š)', 'TOM_THE_TOW_TRUCK', 'CARCITY'),
    
    # CAR PATROL
    (r'(?i)(car\s*patrol|super\s*patrouille|streifenwagen|super\s*pattuglia|super\s*patrulla|super\s*patrulha|auto\s*patrouille|auto\s*patrole|autopatrull|masina\s*de\s*patrulare|patrol\s*policyjny|araba\s*devriyesi|autohl[íi]dka|περιπολία|Î—\s*Î ÎµÏ|авто\s*патруль|Ð¿Ð°Ñ‚Ñ€ÑƒÐ»|патрулиращи\s*коли|bilpatrullen|mobil\s*patrol|đội\s*xe\s*tuần\s*tra|消防車とパトカー|カーパトロール|ã‚«ãƒ¼ãƒ‘ãƒˆ|superauto)', 'CAR_PATROL', 'CARCITY'),
    
    # CARL RESCUE (must be evaluated before Super Truck)
    (r'(?i)(carl\s*rescue|super\s*truck\s*rescue)', 'CARL_RESCUE', 'CARCITY_SUPER'),
    
    # SUPER TRUCK / CARL / SPID
    (r'(?i)(super\s*ci[ęe]żar|super\s*truck|super\s*camion|super\s*camión|super\s*caminh[ãa]o|super\s*kamion|supern[áa]kla[ďd][áa]k|s[üu]per\s*kamyon|siêu\s*xe\s*tải|carl.*super|carl.*transform|カール.*トランスフォーマー|カール.*スーパー|カール.*レスキュー|カールトランスフォーマー|superlastbilen|супер\s*камион|супергрузовик\s*карл|Ñ\x81ÑƒÐ¿ÐµÑ€|καρλ|σούペル\s*φορτηγό|ÎšÎ±Ï\x81Î»|spid|スピッド|ãƒ¬ãƒ¼ã‚·ãƒ³ã‚°ã‚«ãƒ¼|スーパートラック)', 'SUPER_TRUCK', 'CARCITY'),
    
    # TROY THE TRAIN
    (r'(?i)(troy.*train|troy.*zug|troy.*treno|troy.*tren|troy.*trem|troy.*trein|trenul\s*troy|tren\s*troy|vl[áa][čc]ek\s*troy|lokomotywa\s*troy|tåget\s*troy|поезд\s*трой|xe\s*lửa\s*troy|rong\s*troy|vlak\s*troy|troy\s*si\s*kereta|τρόυ|τρέノ|Î¤Ï\x81ÏŒÏ…|Ð¿Ð¾ÐµÐ·Ð´\s*Ñ‚Ñ€Ð¾Ð¹|トレインのトロイ|train\s*town|zugstadt)', 'TROY_THE_TRAIN', 'CARCITY'),
    
    # TED THE TRAIN
    (r'(?i)(ted.*train|ted.*zug|ted.*treno|ted.*tren|ted.*trem|ted.*trein|ted.*poci|trenul\s*ted|tren\s*ted|поезд\s*тед|Ð¿Ð¾ÐµÐ·Ð´\s*Ð¢ÐµÐ´|トレインのテッド|テッド.*トレイン|トレインと一緒に学ぼう|ãƒˆãƒ¬ã‚¤ãƒ³ã\x81®ãƒ†ãƒƒãƒ‰)', 'TED_THE_TRAIN', 'LEARN_TV'),
    
    # CONSTRUCTION SQUAD
    (r'(?i)(construction\s*squad|camions\s*constructeurs|bau\s*trupp|squadra\s*di\s*costruzione|caminh[õo]es.*constru[çc][ãa]o|caminhaos.*constru|equipo\s*constructor|mini\s*constructores|in[şs]aat\s*ekibi|ekipa\s*budowla|bouwgroep|echipa\s*de\s*constructii|строительная\s*бригада|Ñ\x81Ñ‚Ñ€Ð¾Ð¸Ñ‚|bygg[äa]nget|đội\s*thi\s*công|å»ºè¨|建設チーム)', 'CONSTRUCTION_SQUAD', 'CARCITY'),
    
    # ETHAN THE DUMP TRUCK
    (r'(?i)(ethan.*dump\s*truck|ethan.*camion\s*benne|ethan.*kipplaster|ethan.*autoribaltabile|ethan.*caminh[ãa]o.*basculante|ethan.*cami[óo]n.*volquete|ethan.*wywrotka|ethan.*volqueta|invata\s*cu\s*camionul\s*ethan|camionul\s*ethan|damperli\s*kamyon\s*ethan|игорь|игорем|самосвалом\s*игорем|Ð˜Ð³Ð¾Ñ€|ダンプトラックのイーサン|ãƒ€ãƒ³ãƒ—ãƒˆãƒ©ãƒƒã‚¯)', 'ETHAN_THE_DUMP_TRUCK', 'LEARN_TV'),
    
    # AMBER THE AMBULANCE
    (r'(?i)(amber.*ambulance|amber.*krankenwagen|amber.*ambulanza|amber.*ambulancia|amber.*ambul[âa]ncia|ambulansen\s*amber)', 'AMBER_THE_AMBULANCE', 'CARCITY'),
    
    # DINO THE DINOSAUR / JEPPY / LEARN TV
    (r'(?i)(dino.*dinos[a-z]+|dino\s*dem\s*dinosaurier|dino\s*il\s*dinosauro|dino\s*o\s*dinossauro|dino\s*el\s*dinosaurio|dino\s*dinozaur|dinozor\s*dino|apprendre\s*avec\s*dino|invata\s*cu\s*dino|lerne.*dino|learn.*dino|aprende.*dino|учите\s*вместе\s*с\s*дино|Ð”Ð¸Ð½Ð¾|恐竜のダイノ|ãƒ€ã‚¤ãƒŽ|æ\x81\x90ç«œ|jeppy|ジッピー|ã‚¸ãƒƒãƒ”ãƒ¼|learn\s*tv)', 'DINO_THE_DINOSAUR', 'LEARN_TV'),
    
    # TINY TRUCKS
    (r'(?i)(tiny\s*trucks|camioncini|piccoli\s*camion|kleinen?\s*trucks|mini\s*camiones|mini\s*caminh[õo]es|minik\s*kamyonlar|małe\s*samochodziki|camioane\s*mici|маленькими\s*грузовичками|Ð¼Ð°Ð»ÐµÐ½ÑŒÐºÐ¸Ð¼Ð¸|小型トラック|å°\x8fåž‹ãƒˆãƒ©ãƒƒã‚¯|carnivale|タイニートラック|ã‚¿ã‚¤ãƒ‹ãƒ¼ãƒˆãƒ©ãƒƒã‚¯)', 'TINY_TRUCKS', 'TINY_WORLD'),
    
    # TINY TOWN
    (r'(?i)(tiny\s*town|ciudad\s*mini|mini\s*cidade|winzige\s*stadt|ã‚¿ã‚¤ãƒ‹ãƒ¼ã‚¿ã‚¦ãƒ³)', 'TINY_TOWN', 'TINY_WORLD'),
    
    # TINY CARS
    (r'(?i)(tiny\s*cars)', 'TINYCARS', 'SHADOW'),
    
    # ANIMACARS
    (r'(?i)(animacars.*daily\s*life|animacars.*vida\s*cotidiana)', 'ANIMACARS_DAILY_LIFE', 'ANIMACARS'),
    (r'(?i)(animacars.*learn|animacars.*aprende)', 'ANIMACARS_LEARNING', 'ANIMACARS'),
    (r'(?i)(animacars.*discovery)', 'ANIMACARS_DISCOVERY', 'ANIMACARS'),
    (r'(?i)(animacars|anima\s*town|アニマカーズ)', None, 'ANIMACARS'),
    
    # MONSTER TOWN / TRUCKS
    (r'(?i)(monster\s*town|monster\s*trucks|lucas.*monster|lucas.*camion|モンスタートラック|ãƒ¢ãƒ³ã‚¹ã‚¿ãƒ¼ãƒˆãƒ©ãƒƒã‚¯)', 'MONSTER_TOWN', 'CARCITY'),
    
    # SHARK ACADEMY
    (r'(?i)(shark\s*academy|sharkies|shark\s*city|シャーク・アカデミー)', 'SHARKS_NARRATIVES', 'SHARK_ACADEMY'),
    
    # THE SUPERS
    (r'(?i)(the\s*supers|super\s*heros|super\s*héros|super\s*héroes)', 'SUPER_HEROS', 'SUPERS'),
    
    # ONE ZEES
    (r'(?i)(one\s*zeez)', 'ONE_ZEES_S1', 'ONE_ZEES'),
    
    # MILIKI
    (r'(?i)(miliki)', 'MILIKI_SHORTS', 'MILIKI'),
    
    # PLUM
    (r'(?i)(plum.*witch|plum.*sorci[èe]re|plum.*bruja|plum.*hexe)', 'PLUM_SUPERWITCH', 'PLUM'),
    
    # ALADDIN
    (r'(?i)(aladdin|アラジン|outrageous\s*series)', 'ALLADIN', 'ALLADIN'),
    
    # BIRDIE
    (r'(?i)\bbirdie\b', 'BIRDIE', 'BIRDIE'),
    
    # LILY
    (r'(?i)(lily.*lovely.*song|lily.*song)', 'LILYS_LOVELY_SONG', 'LILY'),
    
    # BABIES IN CAR CITY / BABY TRUCKS
    (r'(?i)(babies\s*in\s*car\s*city|baby\s*trucks|go\s*go\s*babies|b[ée]b[ée]s\s*dans\s*la\s*ville|bebes\s*en\s*auto\s*city|piccoli\s*a\s*car\s*city|малыши\s*в\s*автомобильном\s*городе|ville\s*des\s*voitures)', 'BABIES_IN_CARCITY', 'CARCITY'),
    
    # ACTION
    (r'(?i)^action$', 'ACTION', 'ACTION'),
    
    # JONNY & FRIENDS
    (r'(?i)(jonny\s*(&|and)\s*friends)', 'CAR_PATROL', 'CARCITY'),
    
    # CAR CITY (Fallback general / Compilation omnibus)
    (r'(?i)(car\s*city|cité\s*des\s*camions|autostadt|autostad|autopolis|città\s*dell\'auto|ciudad\s*de\s*autos|cidade\s*dos\s*carros|orasul\s*masinilor|bilk[öa]ping|カーシティ|カーシティー|ã‚«ãƒ¼ã‚·ãƒ†)', None, 'CARCITY'),
]


def resolve_canonical_series(text: str | None) -> str | None:
    """Retorna el nombre canónico de la serie Broadkast a partir de cualquier alias multilingüe."""
    if not text or not isinstance(text, str):
        return None
    variants = _try_decode_mojibake(text)
    for variant in variants:
        for pat, bk_series, _ in SERIES_RULES:
            if bk_series and re.search(pat, variant):
                return bk_series
    return None


def resolve_franchise_project(text: str | None) -> str | None:
    """Retorna el nombre canónico de la franquicia/proyecto Broadkast a partir de cualquier alias multilingüe."""
    if not text or not isinstance(text, str):
        return None
    variants = _try_decode_mojibake(text)
    for variant in variants:
        for pat, _, proj in SERIES_RULES:
            if proj and re.search(pat, variant):
                return proj
    return None


def is_alien_series(text: str | None) -> bool:
    """Verifica si el texto corresponde a una serie ajena a Amuse (Blacklist)."""
    if not text or not isinstance(text, str):
        return False
    variants = _try_decode_mojibake(text)
    for variant in variants:
        if any(re.search(pat, variant) for pat in ALIEN_SERIES_PATTERNS):
            return True
    return False


def is_thematic_prefix(text: str | None) -> bool:
    """Verifica si el prefijo es una etiqueta festiva, estacional o didáctica."""
    if not text or not isinstance(text, str):
        return False
    variants = _try_decode_mojibake(text.strip())
    for variant in variants:
        if any(re.search(pat, variant) for pat in THEMATIC_PREFIX_PATTERNS):
            return True
    return False


def resolve_constraint(amz_series: str | None, raw_title: str | None = None) -> str | None:
    """
    Determina la restricción más precisa para matching:
    1. Si se detecta una serie canónica específica (del título o de Amazon series), retorna el nombre de serie.
    2. Si no hay serie específica pero sí franquicia (ej. 'CARCITY', 'ANIMACARS', 'LEARN_TV', 'SHARK_ACADEMY'), retorna la franquicia.
    3. Si no se detecta ninguna, retorna None.
    """
    # 1. Prefer specific series from title (e.g. "Tom the Tow Truck: Episode") or from amz_series
    s_from_title = None
    if raw_title:
        s_from_title, _ = extract_title_and_series(raw_title, amz_series)
    if s_from_title:
        return s_from_title

    s_from_series = resolve_canonical_series(amz_series)
    if s_from_series:
        return s_from_series

    # 2. Franchise project fallback
    p_from_series = resolve_franchise_project(amz_series)
    if p_from_series:
        return p_from_series

    if raw_title:
        p_from_title = resolve_franchise_project(raw_title)
        if p_from_title:
            return p_from_title

    return None


def extract_title_and_series(raw_title: str, amz_series: str | None = None) -> tuple[str | None, str]:
    """
    Analiza el título de Amazon y su posible serie.
    Retorna (canonical_series_constraint, clean_title_for_matching).
    
    Reglas:
    1. Si la serie de Amazon ya indica una serie o franquicia específica, esa tiene preferencia.
    2. Si el título tiene ':' o '：', evalúa si es formato 'Episodio : Serie' (común en JP/PT)
       o 'Serie : Episodio' (estilo occidental):
       - Si el prefijo identifica una serie y amz_series no la contradecía, se usa como serie.
       - Si el sufijo identifica la serie y el prefijo es el episodio, se extrae el episodio.
       - Si el prefijo es temático (ej. 'Halloween:', 'Christmas:'), se remueve el prefijo temático.
    3. No permite que palabras clave en el título de un episodio (ej. 'car wash', 'superhero')
       secuestren la serie si la serie ya está fijada en otra franquicia (ej. TINY_WORLD).
    """
    clean_title = raw_title.strip()
    detected_series = resolve_canonical_series(amz_series)
    detected_proj = resolve_franchise_project(amz_series)
    
    colon_sep = None
    if ':' in clean_title:
        colon_sep = ':'
    elif '：' in clean_title:
        colon_sep = '：'
        
    if colon_sep:
        parts = clean_title.split(colon_sep, 1)
        prefix = re.sub(r'^[\[\(\"\'【]+|[\]\)\"\'】]+$', '', parts[0]).strip()
        remainder = parts[1].strip()
        
        prefix_series = resolve_canonical_series(prefix)
        prefix_proj = resolve_franchise_project(prefix)
        remainder_series = resolve_canonical_series(remainder)
        remainder_proj = resolve_franchise_project(remainder)
        
        # In Japanese / Portuguese, format can often be 'Episode Title : Show Name'
        if remainder_series and (not prefix_series or remainder_series == detected_series):
            if not detected_series:
                detected_series = remainder_series
            clean_title = prefix if prefix else clean_title
        elif prefix_series:
            if not detected_series:
                detected_series = prefix_series
                clean_title = remainder if remainder else clean_title
            elif detected_series == prefix_series:
                clean_title = remainder if remainder else clean_title
            else:
                # Cross-franchise protection: do not let a title keyword hijack a different franchise!
                if detected_proj and prefix_proj and detected_proj != prefix_proj:
                    clean_title = remainder if remainder else clean_title
                elif detected_series in ('CARCITY', 'ANIMACARS', 'LEARN_TV'):
                    detected_series = prefix_series
                    clean_title = remainder if remainder else clean_title
        elif is_thematic_prefix(prefix):
            clean_title = remainder if remainder else clean_title
            
    # Si aún no detectamos serie del prefijo ni de amz_series, buscar en el título completo
    if not detected_series:
        detected_series = resolve_canonical_series(raw_title)
        
    return detected_series, clean_title
