"""Unit tests for the multilingual series and franchise alias resolver."""

import pytest
from core.normalization.series_alias import (
    extract_title_and_series,
    is_alien_series,
    is_thematic_prefix,
    resolve_canonical_series,
    resolve_franchise_project,
)


def test_increditales_multilingual():
    """Verify Increditales alias detection across languages and scripts."""
    cases = [
        ("Increditales", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("IncrediTales: País das Maravilhas do Inverno", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("Increditales: 踊って笑って", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("インクレディテールズ", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("おとぎ話", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("Märchen für Kinder", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("Fairy Tales for Kids", "INCREDITALES_SKETCHES", "INCREDITALES"),
        ("Increditales: Adorável demais para assustar", "INCREDITALES_SKETCHES", "INCREDITALES"),
    ]
    for text, expected_series, expected_project in cases:
        assert resolve_canonical_series(text) == expected_series, f"Failed for {text}"
        assert resolve_franchise_project(text) == expected_project, f"Failed project for {text}"


def test_tom_franchise_multilingual():
    """Verify Tom Tow Truck, Paint Shop, Car Wash, and Garage across languages."""
    # Paint Shop
    paint_cases = [
        "Tom The Tow Truck's Paint Shop",
        "L'Atelier de Peinture de Tom",
        "Die Lackierwerkstatt von Tom dem Abschleppwagen",
        "L'Officina di Verniciatura di Tom il Carro Attrezzi",
        "Oficina de Pintura do TOM",
        "Vopsitoria lui Tom",
        "Tomova autolakovna",
        "Lakiernia Toma",
        "το βαφείο του τομ",
        "cửa hàng sơn của Tom",
        "малярная мастерская тома",
        "レッカー車のトムのペイントショップ",
        "トムのペイントショップ",
    ]
    for text in paint_cases:
        assert resolve_canonical_series(text) == "TOM_PAINT_SHOP", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"

    # Car Wash
    wash_cases = [
        "Tom's Car Wash",
        "Le Lavage Auto de Tom",
        "Die Autowaschanlage von Tom",
        "L'Autolavaggio di Tom il Carro Attrezzi",
        "Lavado de autos de Tom",
        "A lavagem de Carros de Tom",
        "Tomovo Umývání Auta",
        "Myjnia Samochodowa Toma",
        "Tom'un Oto Yıkamacısı",
        "Το πλυντήριο αυτοκινήτων του Tom",
        "автомойка тома",
        "トムの洗車場",
    ]
    for text in wash_cases:
        assert resolve_canonical_series(text) == "TOMS_CAR_WASH", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"

    # Tow Truck
    tow_cases = [
        "Tom The Tow Truck",
        "Tom la Dépanneuse",
        "Tom der Abschleppwagen",
        "Tom il Carro Attrezzi",
        "Tom la Grúa",
        "Tom o Caminhão de Reboque",
        "Tom de takelwagen",
        "Tom camionul de tractari",
        "Odtahové auto Tom",
        "Tom Holownik",
        "Том Аварийката",
        "эвакуатор Том",
        "Puksiirauto Tom",
        "Çekici Tom",
        "Τομ το Ρυμουλκό",
        "レッカー車のトム",
    ]
    for text in tow_cases:
        assert resolve_canonical_series(text) == "TOM_THE_TOW_TRUCK", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"

    # Garage
    assert resolve_canonical_series("Tom's Garage") == "TOMS_GARAGE"
    assert resolve_franchise_project("Tom's Garage") == "CARCITY_SUPER"


def test_car_patrol_multilingual():
    """Verify Car Patrol aliases across languages."""
    cases = [
        "Car Patrol of Car City",
        "La Super Patrouille",
        "Der Streifenwagen in Autopolis",
        "La Super Pattuglia",
        "La Super Patrulla",
        "Super Patrulha",
        "Auto patrouille",
        "Masina de patrulare",
        "Patrol Policyjny",
        "Araba Devriyesi",
        "Autohlídka",
        "Η Περιπολία Αυτοκινήτων",
        "авто патруль",
        "патрулиращи коли",
        "カーパトロール",
    ]
    for text in cases:
        assert resolve_canonical_series(text) == "CAR_PATROL", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"


def test_super_truck_and_carl_rescue():
    """Verify Super Truck and Carl Rescue aliases."""
    # Carl Rescue
    assert resolve_canonical_series("Carl Rescue") == "CARL_RESCUE"
    assert resolve_canonical_series("Super Truck Rescue") == "CARL_RESCUE"
    assert resolve_franchise_project("Carl Rescue") == "CARCITY_SUPER"

    # Super Truck / Carl
    cases = [
        "Super Truck",
        "Carl le Super Camion",
        "Super Truck in Autopolis",
        "Carl il Super Camion",
        "Super Camión",
        "Super Caminhão",
        "Superlastbilen",
        "Super Ciężarówka",
        "Supernáklaďák",
        "Süper Kamyon Carl",
        "Супер Камиона Карл",
        "супергрузовик Карл",
        "Καρλ το Σούπερ Φορτηγό",
        "Siêu xe tải Carl",
        "スーパートラック",
        "Spid el coche de carreras",
        "Spid the racing car",
    ]
    for text in cases:
        assert resolve_canonical_series(text) == "SUPER_TRUCK", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"


def test_train_series_multilingual():
    """Verify Troy the Train and Ted the Train."""
    troy_cases = [
        "Troy The Train",
        "Troy le Train",
        "Troy der Zug in Autopolis",
        "Troy il Treno in Car City",
        "Troy el Tren",
        "Troy o Trem",
        "Troy de trein",
        "Trenul Troy",
        "Vláček Troy",
        "Lokomotywa Troy",
        "поезд трой",
        "Τρόυ το τρένο",
        "トレインのトロイ",
    ]
    for text in troy_cases:
        assert resolve_canonical_series(text) == "TROY_THE_TRAIN", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"

    ted_cases = [
        "Ted the Train",
        "Ted der Zug",
        "Ted el tren",
        "Trenul Ted",
        "поезд Тед",
        "トレインと一緒に学ぼう",
    ]
    for text in ted_cases:
        assert resolve_canonical_series(text) == "TED_THE_TRAIN", f"Failed for {text}"
        assert resolve_franchise_project(text) == "LEARN_TV"


def test_construction_squad_multilingual():
    """Verify Construction Squad across languages."""
    cases = [
        "Construction Squad",
        "Les Camions Constructeurs",
        "Der Bau Trupp",
        "La Squadra di Costruzione",
        "Equipo Constructor",
        "Caminhões de Construção",
        "Bouwgroep",
        "Echipa de Constructii",
        "Ekipa Budowlana",
        "İnşaat Ekibi",
        "строительная бригада",
        "đội thi công",
        "建設チーム",
    ]
    for text in cases:
        assert resolve_canonical_series(text) == "CONSTRUCTION_SQUAD", f"Failed for {text}"
        assert resolve_franchise_project(text) == "CARCITY"


def test_ethan_and_dino_and_jeppy():
    """Verify Ethan the Dump Truck, Dino the Dinosaur, and Jeppy."""
    ethan_cases = [
        "Ethan the Dump Truck",
        "Ethan le Camion Benne",
        "Ethan der Kipplaster",
        "Ethan l'Autoribaltabile",
        "Ethan el Camión Volquete",
        "Ethan o Caminhão Basculante",
        "Ethan Wywrotka",
        "Camionul Ethan",
        "Damperli kamyon Ethan",
        "самосвал Игорь",
        "ダンプトラックのイーサン",
    ]
    for text in ethan_cases:
        assert resolve_canonical_series(text) == "ETHAN_THE_DUMP_TRUCK", f"Failed for {text}"
        assert resolve_franchise_project(text) == "LEARN_TV"

    dino_cases = [
        "Dino the Dinosaur",
        "Apprendre avec Dino",
        "Lerne Farben mit Dino dem Dinosaurier",
        "Dino il Dinosauro",
        "Dino el Dinosaurio",
        "Dino o Dinossauro",
        "Invata cu Dino",
        "Dino Dinozaur",
        "Dinozor Dino",
        "учите вместе с Дино",
        "恐竜のダイノ",
        "Learn with Jeppy",
        "Lerne mit Jeppy",
        "Aprende con Jeppy",
        "ジッピーと数字を学ぼう",
    ]
    for text in dino_cases:
        assert resolve_canonical_series(text) == "DINO_THE_DINOSAUR", f"Failed for {text}"
        assert resolve_franchise_project(text) == "LEARN_TV"


def test_mojibake_tolerance():
    """Verify that common CP1252/Latin-1 double-encoding issues are handled gracefully."""
    mojibake_cases = [
        ("Tom la DÃ©panneuse", "TOM_THE_TOW_TRUCK"),
        ("Super CamiÃ³n", "SUPER_TRUCK"),
        ("Tom o CaminhÃ£o de Reboque", "TOM_THE_TOW_TRUCK"),
        ("Ethan o CaminhÃ£o Basculante", "ETHAN_THE_DUMP_TRUCK"),
        ("Tom la GrÃºa", "TOM_THE_TOW_TRUCK"),
        ("BÃ¤rgningsbilen Tom i BilkÃ¶ping", "TOM_THE_TOW_TRUCK"),
        ("Super CiÄ™Å¼arÃ³wka", "SUPER_TRUCK"),
    ]
    for mojibake, expected_series in mojibake_cases:
        assert resolve_canonical_series(mojibake) == expected_series, f"Failed for {mojibake}"


def test_alien_series_detection():
    """Verify that alien series across languages are accurately flagged for rejection."""
    aliens = [
        "Molang",
        "Моланг",
        "モラン",
        "Mouk",
        "Mokon suuri maailma",
        "ムーク",
        "Louie",
        "Didou",
        "Luluś",
        "64 Zoo Lane",
        "calle del zoológico 64",
        "動物園通り64番地",
        "Diego & Ziggy",
        "Superzoo",
        "Groovy the Martian",
        "Pipo",
        "Cool City",
        "Jasper the Penguin",
    ]
    for alien in aliens:
        assert is_alien_series(alien) is True, f"Failed to detect alien: {alien}"

    amuse_ips = [
        "Increditales",
        "Car City",
        "Tom the Tow Truck",
        "Super Truck",
        "Shark Academy",
        "AnimaCars",
        "Amber the Ambulance",
        "Troy the Train",
        "Ethan the Dump Truck",
        "Dino the Dinosaur",
        "Miliki",
    ]
    for ip in amuse_ips:
        assert is_alien_series(ip) is False, f"False positive alien detection: {ip}"


def test_thematic_prefix_detection():
    """Verify that seasonal/thematic prefixes are recognized."""
    thematics = [
        "Halloween:",
        "Christmas Special:",
        "Navidad:",
        "Natale:",
        "Weihnachten:",
        "Easter:",
        "Pascua:",
        "Pâques:",
        "Ostern:",
        "Summer:",
        "Verano:",
        "Verão:",
        "Estate:",
        "Winter:",
        "Inverno:",
        "Spring:",
        "Primavera:",
        "Thanksgiving:",
        "Acción de Gracias:",
        "April Fool:",
        "Prima Aprilis:",
        "Día de los Inocentes:",
        "Learn colors:",
        "Aprende los números:",
        "Back to School:",
        "Volta às aulas:",
    ]
    for th in thematics:
        prefix = th.rstrip(":")
        assert is_thematic_prefix(prefix) is True, f"Failed thematic: {prefix}"

    non_thematics = [
        "Increditales",
        "Super Truck",
        "Carl le Super Camion",
        "Tom the Tow Truck",
        "Shark Academy",
    ]
    for nth in non_thematics:
        assert is_thematic_prefix(nth) is False, f"False thematic: {nth}"


def test_extract_title_and_series():
    """Verify the core title and series extractor under multiple conditions."""
    # 1. The user's false positive: Increditales: País das Maravilhas do Inverno
    ser, clean = extract_title_and_series(
        "Increditales: País das Maravilhas do Inverno",
        "Increditales: País das Maravilhas do Inverno",
    )
    assert ser == "INCREDITALES_SKETCHES"
    assert clean == "País das Maravilhas do Inverno"

    # 2. Thematic prefix: Halloween : The Spooky Ghost with specific Car Patrol series
    ser, clean = extract_title_and_series(
        "Halloween : The Spooky Ghost",
        "Car Patrol of Car City",
    )
    assert ser == "CAR_PATROL"  # Inherited from specific amz_series
    assert clean == "The Spooky Ghost"

    # 2b. Thematic prefix with generic Car City omnibus: resolves to CARCITY franchise constraint
    from core.normalization.series_alias import resolve_constraint
    constraint = resolve_constraint("Car City", "Halloween : The Spooky Ghost")
    assert constraint == "CARCITY"

    # 3. Franchise prefix inside title when series is generic
    ser, clean = extract_title_and_series(
        "Carl le Super Camion : Le Monstre de Boue",
        "Car City",
    )
    assert ser == "SUPER_TRUCK"  # More specific prefix overrides generic Car City
    assert clean == "Le Monstre de Boue"

    # 4. Standard clean title without prefix
    ser, clean = extract_title_and_series(
        "Charlie The Spider-Man",
        "L'Officina di Verniciatura di Tom il Carro Attrezzi",
    )
    assert ser == "TOM_PAINT_SHOP"
    assert clean == "Charlie The Spider-Man"

