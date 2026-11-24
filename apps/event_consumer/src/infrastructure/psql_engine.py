import urllib.parse
from sqlalchemy import create_engine, Engine

def create_postgres_engine(user: str, password: str, host: str, port: str, db_name: str) -> Engine:

    if not all([user, password, host, port, db_name]):
        raise ValueError("[Error] - Missing PostgreSQL connection parameters. Please provide user, password, host, port, and db_name.")

    escaped_user = urllib.parse.quote_plus(user)
    escaped_password = urllib.parse.quote_plus(password)

    database_url = f"postgresql+psycopg2://{escaped_user}:{escaped_password}@{host}:{port}/{db_name}"
    
    return create_engine(
        database_url, 
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10
    )