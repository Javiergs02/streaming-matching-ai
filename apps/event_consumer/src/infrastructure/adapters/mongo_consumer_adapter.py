from typing import List, Optional, Iterable
from pymongo import MongoClient
from domain.ports import EventConsumerRepository

class MongoConsumerRepository(EventConsumerRepository):
    def __init__(self, client: MongoClient, db_name: str):
        self.client = client
        self.db = self.client[db_name]

    def get_unprocessed_events(
        self, 
        collection_name: str, 
        event_types: Optional[List[str]] = None
    ) -> Iterable[dict]:
        coll = self.db[collection_name]

        # Excluir eventos que ya fallaron para evitar bucle infinito de reintentos (Fix C35)
        query = {
            "$and": [
                {
                    "$or": [
                        {"metadata.processed_in_psql": {"$exists": False}},
                        {"metadata.processed_in_psql": False}
                    ]
                },
                {"metadata.consumer_error": {"$ne": True}}
            ]
        }

        if event_types:
            query["metadata.event_type"] = {"$in": event_types}

        return list(coll.find(query).sort("metadata.occurred_at", 1))

    def mark_as_processed(self, collection_name: str, event_ids: List[str]) -> None:
        if not event_ids:
            return
            
        coll = self.db[collection_name]
        coll.update_many(
            {"_id": {"$in": event_ids}},
            {"$set": {"metadata.processed_in_psql": True}}
        )

    def mark_as_failed(self, collection_name: str, event_id: str, error_message: str) -> None:
        coll = self.db[collection_name]
        coll.update_one(
            {"_id": event_id},
            {
                "$set": {
                    "metadata.processed_in_psql": False,
                    "metadata.consumer_error": True,
                    "metadata.error_message": error_message
                }
            }
        )

    def close(self) -> None:
        self.client.close()