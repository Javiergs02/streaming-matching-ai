import hashlib
import json
from datetime import datetime, date
from typing import List, Set, Tuple
from domain.ports import EventRepository
from pymongo import MongoClient, UpdateOne

class MongoRepository(EventRepository):
    def __init__(self, uri: str, db_name: str):
        self.uri = uri
        self.db_name = db_name
        self.client = MongoClient(self.uri)
        self.db = self.client[self.db_name]

    def get_last_stats_date(self, video_ids: list[str], collection_name: str, by_country: bool = False, max_date: str = None, only_monetized: bool = False) -> dict[str, date]:
        if not video_ids:
            return {}

        coll = self.db[collection_name]
        
        match_stage = {"payload.video_id": {"$in": video_ids}}
        if by_country:
            match_stage["payload.geography"] = {"$nin": ["Global", "Unknown Geo", None]}
        else:
            match_stage["payload.geography"] = {"$in": ["Global", "Unknown Geo", None]}

        if only_monetized:
            match_stage["$or"] = [
                {"payload.estimated_revenue": {"$gt": 0}},
                {"payload.views": {"$lte": 0}},
                {"payload.extra_metrics.views": {"$lte": 0}}
            ]

        if max_date:
            max_date_str = max_date.strftime("%Y-%m-%d") if hasattr(max_date, "strftime") else str(max_date)
            match_stage["payload.date"] = {"$lte": max_date_str}

        pipeline = [
            {"$match": match_stage},
            {"$group": {
                "_id": "$payload.video_id",
                "max_date": {"$max": "$payload.date"}
            }}
        ]
        
        cursor = coll.aggregate(pipeline)
        last_dates = {}
        
        for doc in cursor:
            v_id = doc["_id"]
            m_date = doc["max_date"]
            
            if not m_date:
                continue
                
            if isinstance(m_date, str):
                last_dates[v_id] = datetime.strptime(m_date, "%Y-%m-%d").date()
            elif hasattr(m_date, "date"):
                last_dates[v_id] = m_date.date()
            else:
                last_dates[v_id] = m_date
                
        return last_dates

    def get_existing_combinations(self, platform: str, dates: list, collection_name: str, video_ids: list = None, exclude_zero_revenue: bool = False, by_country: bool = False) -> Set[Tuple]:
        if not dates:
            return set()
            
        coll = self.db[collection_name]
        
        query = {
            "metadata.event_type": {"$regex": f"^{platform}"},
            "payload.date": {"$in": dates}
        }

        if by_country:
            query["payload.geography"] = {"$nin": ["Global", "Unknown Geo", None]}
        else:
            query["payload.geography"] = {"$in": ["Global", "Unknown Geo", None]}

        if exclude_zero_revenue:
            query["$or"] = [
                {"payload.estimated_revenue": {"$gt": 0}},
                {"payload.views": {"$lte": 0}},
                {"payload.extra_metrics.views": {"$lte": 0}}
            ]
        
        if video_ids:
            query["payload.video_id"] = {"$in": video_ids}
        
        cursor = coll.find(query, {"payload.video_id": 1, "payload.date": 1, "payload.geography": 1, "_id": 0})
        
        existing_records = set()
        for doc in cursor:
            payload = doc.get("payload", {})
            v_id = payload.get("video_id")
            d_str = payload.get("date")
            geo = payload.get("geography", "Unknown Geo")
            if v_id and d_str:
                if by_country:
                    existing_records.add((str(v_id), str(d_str), str(geo)))
                else:
                    existing_records.add((str(v_id), str(d_str)))
                
        return existing_records

    def publish(self, events: List[dict], collection: str) -> dict:
        if not events:
            return {"published_news": 0, "ignored_duplicates": 0}

        target_coll = collection
        existing_collections = self.db.list_collection_names()
        if target_coll not in existing_collections:
            raise ValueError(
                f"[CRITICAL MONGO ERROR] Collection '{target_coll}' does NOT exist "
                f"in database '{self.db_name}'. Execution aborted to prevent automatic creation. "
                f"Available collections: {existing_collections}"
            )

        coll = self.db[target_coll]
        operations = []
        
        for event in events:
            event_id = event.get("_id") or self._generate_fingerprint(event)
            
            event_to_persist = event.copy()
            event_to_persist["_id"] = event_id

            p = event.get("payload", {})
            m = event.get("metadata", {})
            vid = p.get("video_id")
            ev_date = p.get("date")
            geo = p.get("geography", "Global")
            ev_type = m.get("event_type")

            if vid and ev_date and ev_type:
                geo_filter = {"$in": ["Global", "Unknown Geo", None]} if geo in ("Global", "Unknown Geo", None) else str(geo)
                filter_query = {
                    "metadata.event_type": ev_type,
                    "payload.video_id": str(vid),
                    "payload.date": str(ev_date),
                    "payload.geography": geo_filter,
                }
                doc_to_set = {k: v for k, v in event_to_persist.items() if k != "_id"}
                operations.append(
                    UpdateOne(
                        filter_query,
                        {
                            "$set": doc_to_set,
                            "$setOnInsert": {"_id": event_id}
                        },
                        upsert=True
                    )
                )
            else:
                operations.append(
                    UpdateOne(
                        {"_id": event_id},
                        {"$setOnInsert": event_to_persist},
                        upsert=True
                    )
                )
            
        if operations:
            result = coll.bulk_write(operations)
            return {
                "published_news": result.upserted_count + result.modified_count,
                "ignored_duplicates": result.matched_count - result.modified_count
            }
            
        return {"published_news": 0, "ignored_duplicates": 0}

    def _generate_fingerprint(self, event: dict) -> str:
        identity_data = {
            "event_type": event.get("metadata", {}).get("event_type"),
            "resource_id": event.get("metadata", {}).get("resource_id"),
            "payload": event.get("payload") 
        }
        
        if not identity_data["event_type"] or not identity_data["payload"]:
            identity_data = event
        
        event_str = json.dumps(identity_data, sort_keys=True, default=str)
        return hashlib.sha256(event_str.encode()).hexdigest()

    def close(self):
        self.client.close()