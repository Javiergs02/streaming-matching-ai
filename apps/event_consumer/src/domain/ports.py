from abc import ABC, abstractmethod
from typing import List, Optional, Iterable

class EventConsumerRepository(ABC):
    @abstractmethod
    def get_unprocessed_events(self, collection_name: str, event_types: Optional[List[str]] = None) -> Iterable[dict]:
        pass
    
    @abstractmethod
    def mark_as_processed(self, collection_name: str, event_ids: List[str]) -> None:
        pass

    @abstractmethod
    def mark_as_failed(self, collection_name: str, event_id: str, error_message: str) -> None:
        pass

class SQLStateRepository(ABC):
    @abstractmethod
    def execute_update(self, query_string: str, params: dict) -> None:
        pass

    @abstractmethod
    def fetch_all(self, query_string: str, params: Optional[dict] = None) -> List[dict]:
        pass