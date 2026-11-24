import re
from sqlalchemy import text
from domain.ports import ChannelRepository
from domain.models import Channel


def _validate_identifier(ident: str) -> str:
    if not ident or not re.match(r"^[a-zA-Z_][a-zA-Z0-9_\.]*$", str(ident).strip()):
        raise ValueError(f"Invalid SQL identifier: {ident}")
    return str(ident).strip()


class YoutubeChannelPostgresRepository(ChannelRepository):
    def __init__(self, engine, table_name, column_mapping: dict):
        self.engine = engine
        self.table_name = _validate_identifier(table_name)
        self.cols = {k: _validate_identifier(v) for k, v in column_mapping.items()} 

    def get_existing_ids(self) -> set[str]:
        query = text(f"SELECT {self.cols['id']} FROM {self.table_name}")
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchall()
            return {row[0] for row in result}

    def get_all_channels(self) -> list[Channel]:
        query = text(f"""
            SELECT 
                {self.cols['id']}, 
                {self.cols['title']}, 
                {self.cols['country']}, 
                {self.cols['monetization']} 
            FROM {self.table_name}
        """)
        
        with self.engine.connect() as conn:
            result = conn.execute(query).fetchall()
            return [
                Channel(
                    channel_id=row[0],
                    platform="youtube",
                    title=row[1] if row[1] else "",
                    description="",
                    country_code=row[2] if row[2] else "",
                    extra_data={
                        "is_monetization_enabled": bool(row[3])
                    }
                ) 
                for row in result
            ]