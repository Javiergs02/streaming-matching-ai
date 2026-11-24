from typing import List, Optional
from sqlalchemy import text
from domain.ports import SQLStateRepository

class PostgresStateRepository(SQLStateRepository):
    def __init__(self, engine):
        self.engine = engine

    def execute_update(self, query_string: str, params: dict) -> None:

        query = text(query_string)
        
        with self.engine.connect() as conn:
            with conn.begin():
                conn.execute(query, params)

    def fetch_all(self, query_string: str, params: Optional[dict] = None) -> List[dict]:
        query = text(query_string)

        with self.engine.connect() as conn:
            result = conn.execute(query, params or {})
            return [dict(row._mapping) for row in result]