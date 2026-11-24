"""Unit tests for domain models."""

from datetime import date
from core.domain.amazon import (
    AmazonPerformanceRecord,
    load_amazon_match_scores,
    get_title_match_score,
    load_amazon_broadkast_titles,
    get_broadkast_title,
)
from core.domain.mapping import ContentMapping, MatchStatus


def test_amazon_performance_record():
    record = AmazonPerformanceRecord(
        date=date(2025, 5, 1),
        title_id="B012345678",
        title_name="Tom the Tow Truck S01E01",
        season_id="S01",
        season_name="Season 1",
        series_id="SER_01",
        series_name="Tom the Tow Truck",
        offer_type="PRIME",
        region="North America",
        territory="US",
        minutes_streamed=125.5,
        unique_streams=25,
        is_movie=False
    )
    assert record.title_name == "Tom the Tow Truck S01E01"
    assert record.minutes_streamed == 125.5
    assert record.unique_streams == 25
    assert record.is_movie is False


def test_content_mapping_unmatched():
    mapping = ContentMapping(
        amazon_title_id="B000TEST",
        amazon_title_name="Unknown Title",
        amazon_normalized_title="unknown title",
        match_status=MatchStatus.UNMATCHED,
        broadkast_content_id="UNMATCHED",
        score=None,
        match_method="heuristic"
    )
    assert mapping.match_status == MatchStatus.UNMATCHED
    assert mapping.broadkast_content_id == "UNMATCHED"
    assert mapping.score is None


def test_amazon_match_scores(tmp_path):
    csv_file = tmp_path / "mappings.csv"
    csv_file.write_text(
        "Amazon Original Title,Match Status,Match Method,Score\n"
        "Title Exact,MATCH,exact_title,1.0\n"
        "Title Semantic,MATCH,semantic_ai,85.4\n"
        "Title Rejected,UNMATCHED,blacklist,N/A\n"
        "Title Low,MATCH,semantic_ai,0.75\n",
        encoding="utf-8"
    )

    scores = load_amazon_match_scores(csv_file)
    assert scores["Title Exact"] == 100.0
    assert scores["Title Semantic"] == 85.4
    assert scores["Title Rejected"] == 0.0
    assert scores["Title Low"] == 75.0

    # Helper tests
    assert get_title_match_score("Title Exact", score_map=scores) == 100.0
    assert get_title_match_score("Title Semantic", score_map=scores) == 85.4
    assert get_title_match_score("Title Rejected", score_map=scores) == 0.0
    assert get_title_match_score("UNMATCHED_AMZ_123", is_unmatched=True, score_map=scores) == 0.0
    assert get_title_match_score(None, score_map=scores) == 0.0
    assert get_title_match_score("Unknown Title", score_map=scores) == 0.0
    assert get_title_match_score("Non existent title", score_map=scores) == 100.0


def test_amazon_broadkast_titles(tmp_path):
    csv_file = tmp_path / "production_mappings.csv"
    csv_file.write_text(
        "Amazon Original Title,Broadkast Assigned Title,Broadkast ID,Broadkast Episode Number,Match Status\n"
        "Mud Trap / The Cold,Mud Trap,EP_2606,24,MATCH\n"
        "Vicky's Plot / The Ball,Vicky's Plot,EP_2595,13,MATCH\n"
        "Fire Rescue / The Climb,Fire Rescue,EP_2597,15,MATCH\n"
        "Generic Ep,ANIMA_TOWN - Ep 99,EP_9999,99,MATCH\n"
        "Unmatched Ep,Some Title,UNMATCHED,N/A,UNMATCHED\n",
        encoding="utf-8"
    )

    titles = load_amazon_broadkast_titles(csv_file)
    assert titles["EP_2606"] == "Mud Trap"
    assert titles["Mud Trap / The Cold"] == "Mud Trap"
    assert titles["EP_2595"] == "Vicky's Plot"
    assert titles["Vicky's Plot / The Ball"] == "Vicky's Plot"
    assert "EP_9999" not in titles
    assert "UNMATCHED" not in titles

    assert get_broadkast_title(bkid="EP_2606", title_map=titles) == "Mud Trap"
    assert get_broadkast_title(amazon_title="Mud Trap / The Cold", title_map=titles) == "Mud Trap"
    assert get_broadkast_title(amazon_title="Unknown Extra", default="Default Title", title_map=titles) == "Default Title"


def test_get_best_english_title():
    from core.domain.amazon import get_best_english_title

    en_map = {
        "EP_2705": ["The Fly Trap", "The TURTLE FIRETRUCK learns GARDENING"],
        "EP_2703": ["The Mud Trap", "The Wrecking Ball LIZARD & bathing can be FUN!"],
        "EP_344": ["Hide-And-Seek", "Tom the Tow Truck Helps Tyler the Race Car"],
        "EP_2744": ["BASKETBALL CROCODILE", "Valentine’s Day: The Flower"],
        "EP_SINGLE": ["Single Title"],
    }

    # Case 1: EP_2705 Spanish Amazon + Japanese/Thai Broadkast Assigned
    res_es = get_best_english_title(
        "EP_2705",
        match_title="ガーデニングを学ぶ消防車カメ",
        amazon_title="Camión Tortuga aprende a jardinear",
        en_map=en_map,
    )
    assert res_es == "The TURTLE FIRETRUCK learns GARDENING"

    res_th = get_best_english_title(
        "EP_2705",
        match_title="เจ้าเต่ารถกับเพลิงเรียนการทำสวน",
        amazon_title="Camión Tortuga aprende a jardinear",
        en_map=en_map,
    )
    assert res_th == "The TURTLE FIRETRUCK learns GARDENING"

    # Case 2: EP_2703 Japanese Amazon + Japanese Broadkast Assigned
    res_lizard = get_best_english_title(
        "EP_2703",
        match_title="レッキングボールトカゲ、お風呂の楽しさを知る",
        amazon_title="トカゲのお風呂",
        en_map=en_map,
    )
    assert res_lizard == "The Wrecking Ball LIZARD & bathing can be FUN!"

    # Case 3: EP_344 German Amazon title
    res_tom = get_best_english_title(
        "EP_344",
        match_title="Tom,camionul de pompieri il ajuta pe Tyler,masina de curse",
        amazon_title="Feuerwehrauto und Tom der Abschleppwagen",
        en_map=en_map,
    )
    assert res_tom == "Tom the Tow Truck Helps Tyler the Race Car"

    # Case 4: EP_2744 Polish Broadkast + English Amazon
    res_val = get_best_english_title(
        "EP_2744",
        match_title="Walentynki: Kwiat",
        amazon_title="[Valentine's Day] The Beautiful Flower /Eagle plane",
        en_map=en_map,
    )
    assert res_val == "Valentine’s Day: The Flower"

    # Single candidate returns immediately
    assert get_best_english_title("EP_SINGLE", en_map=en_map) == "Single Title"

    # Missing ID returns fallback/default
    assert get_best_english_title("EP_MISSING", default="Fallback Title", en_map=en_map) == "Fallback Title"
    assert get_best_english_title(None, amazon_title="Amazon Title", en_map=en_map) == "Amazon Title"




