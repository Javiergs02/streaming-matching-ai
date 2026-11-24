import unittest
from unittest.mock import MagicMock
from core.normalization.youtube_catalog_enrichment import enrich_youtube_collection


class TestYoutubeCatalogEnrichment(unittest.TestCase):
    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_coll = MagicMock()
        self.mock_db.__getitem__.return_value = self.mock_coll

        self.catalog_map = {
            "vid_yt_1": ("CARCITY", "SUPER_TRUCK", "Super Truck Ep 1"),
            "vid_yt_2": ("SHARK_ACADEMY", "SHARKS_RHYMES", "Baby Shark Singalong"),
        }

    def test_enrich_youtube_collection_with_target_videos(self):
        mock_result = MagicMock()
        mock_result.matched_count = 2
        mock_result.modified_count = 2
        self.mock_coll.bulk_write.return_value = mock_result

        res = enrich_youtube_collection(
            self.mock_db,
            "monthly_performance_summaries",
            catalog_map=self.catalog_map,
            target_video_ids=["vid_yt_1", "vid_yt_2"],
            batch_size=10,
        )

        self.assertEqual(res["matched"], 2)
        self.assertEqual(res["modified"], 2)
        self.mock_coll.bulk_write.assert_called_once()
        args, kwargs = self.mock_coll.bulk_write.call_args
        updates = args[0]
        self.assertEqual(len(updates), 2)
        self.assertEqual(updates[0]._filter, {"_id.video_id": "vid_yt_1", "_id.platform": "youtube"})
        self.assertEqual(
            updates[0]._doc,
            {"$set": {"ip_name": "CARCITY", "series_name": "SUPER_TRUCK", "title": "Super Truck Ep 1"}},
        )

    def test_enrich_youtube_collection_all_catalog(self):
        mock_result = MagicMock()
        mock_result.matched_count = 2
        mock_result.modified_count = 2
        self.mock_coll.bulk_write.return_value = mock_result

        res = enrich_youtube_collection(
            self.mock_db,
            "yearly_performance_summaries",
            catalog_map=self.catalog_map,
            target_video_ids=None,
            batch_size=10,
        )

        self.assertEqual(res["matched"], 2)
        self.mock_coll.bulk_write.assert_called_once()
        args, kwargs = self.mock_coll.bulk_write.call_args
        updates = args[0]
        self.assertEqual(len(updates), 2)


if __name__ == "__main__":
    unittest.main()
