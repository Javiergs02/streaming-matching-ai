from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from urllib.parse import quote_plus

def get_db_engine(DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME):
    db_url = URL.create(
        drivername="postgresql+psycopg2",
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME
    )
    
    return create_engine(db_url, pool_pre_ping=True)

def build_mongo_uri(base_uri: str, user: str, password: str) -> str:

    if "://" not in base_uri:
        raise ValueError(f"Invalid MongoDB URI: {base_uri}")

    scheme, rest = base_uri.split("://", 1)
    user_enc = quote_plus(user)
    pass_enc = quote_plus(password)

    uri = f"{scheme}://{user_enc}:{pass_enc}@{rest}"
    separator = "&" if "?" in uri else "?"
    return f"{uri}{separator}authSource=admin"