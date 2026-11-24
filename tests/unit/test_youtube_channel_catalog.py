"""
tests/unit/test_youtube_channel_catalog.py

Unit tests for YouTube channel master catalog and fallback enrichment engine.
"""

import pandas as pd
import pytest

from core.domain.youtube_channels import (
    YouTubeChannelCatalog,
    enrich_youtube_dataframe,
    enrich_youtube_video_metadata,
    get_youtube_channel_info,
    resolve_youtube_channel_ip,
)


@pytest.fixture
def catalog():
    return YouTubeChannelCatalog.get_instance()


def test_catalog_loads_successfully(catalog):
    assert catalog.is_loaded
    channels = catalog.get_all_channels()
    assert len(channels) == 235


def test_known_channels_lookup(catalog):
    # Shark Academy - Songs for kids
    shk_info = get_youtube_channel_info("UCxiOfWB9GnMxjm9pfKbqx1w")
    assert shk_info is not None
    assert shk_info["main_series_ip"] == "Shark Academy"
    assert shk_info["universe"] == "SHK"
    assert shk_info["language"] == "English"

    # Action! - French
    act_info = get_youtube_channel_info("UC4mH_fRtx5aHRKSmLn3jUBA")
    assert act_info is not None
    assert act_info["main_series_ip"] == "Others"
    assert act_info["universe"] == "KICK"

    # Display string with parentheses: 'Shark Academy (UCxiOfWB9GnMxjm9pfKbqx1w)'
    shk_display = get_youtube_channel_info("Shark Academy - Songs for kids (UCxiOfWB9GnMxjm9pfKbqx1w)")
    assert shk_display is not None
    assert shk_display["main_series_ip"] == "Shark Academy"


def test_resolve_channel_ip():
    ip, univ = resolve_youtube_channel_ip("UCxiOfWB9GnMxjm9pfKbqx1w")
    assert ip == "Shark Academy"
    assert univ == "SHK"

    # Unknown channel
    ip_unk, univ_unk = resolve_youtube_channel_ip("UC_NON_EXISTENT_CHANNEL_123")
    assert ip_unk is None
    assert univ_unk is None


def test_enrich_youtube_video_metadata_fallback():
    # Case 1: Video with UNMATCHED IP gets enriched from channel
    series, ip = enrich_youtube_video_metadata(
        channel_id="UCxiOfWB9GnMxjm9pfKbqx1w",
        current_series="UNMATCHED_YT",
        current_ip="UNMATCHED"
    )
    assert ip == "Shark Academy"
    assert series == "Shark Academy"

    # Case 2: Video with ALREADY MATCHED IP is preserved
    series_kept, ip_kept = enrich_youtube_video_metadata(
        channel_id="UCxiOfWB9GnMxjm9pfKbqx1w",
        current_series="Shark Academy Ep 01",
        current_ip="Shark Academy Original"
    )
    assert ip_kept == "Shark Academy Original"
    assert series_kept == "Shark Academy Ep 01"

    # Case 3: Unknown channel preserves unmatched
    series_unk, ip_unk = enrich_youtube_video_metadata(
        channel_id="UC_NON_EXISTENT",
        current_series="UNMATCHED_YT",
        current_ip="UNMATCHED"
    )
    assert ip_unk == "UNMATCHED"
    assert series_unk == "UNMATCHED_YT"


def test_enrich_youtube_dataframe():
    df = pd.DataFrame([
        {
            "video_id": "V1",
            "channel_id": "UCxiOfWB9GnMxjm9pfKbqx1w",
            "series_name": "UNMATCHED_YT",
            "ip_name": "UNMATCHED"
        },
        {
            "video_id": "V2",
            "channel_id": "UCxiOfWB9GnMxjm9pfKbqx1w",
            "series_name": "Shark Academy Real Series",
            "ip_name": "Shark Academy Real IP"
        },
        {
            "video_id": "V3",
            "channel_id": "Action! (UC4mH_fRtx5aHRKSmLn3jUBA)",
            "series_name": "UNMATCHED_YT",
            "ip_name": "UNMATCHED"
        }
    ])

    df_enriched = enrich_youtube_dataframe(df)

    # V1 was UNMATCHED -> resolved to Shark Academy / SHK
    assert df_enriched.loc[0, "ip_name"] == "Shark Academy"
    assert df_enriched.loc[0, "series_name"] == "Shark Academy"
    assert df_enriched.loc[0, "universe"] == "SHK"

    # V2 was already matched -> preserved
    assert df_enriched.loc[1, "ip_name"] == "Shark Academy Real IP"
    assert df_enriched.loc[1, "series_name"] == "Shark Academy Real Series"

    # V3 (Action) was UNMATCHED -> resolved to Others / KICK
    assert df_enriched.loc[2, "ip_name"] == "Others"
    assert df_enriched.loc[2, "universe"] == "KICK"
