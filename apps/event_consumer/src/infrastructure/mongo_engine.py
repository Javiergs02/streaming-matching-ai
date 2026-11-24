from pymongo import MongoClient
import urllib.parse

def create_mongo_client(user: str, password: str, host: str, port: str, auth_db: str) -> MongoClient:

    if not all([user, password, host, port]):
        raise ValueError("[Error] - Missing MongoDB connection parameters. Please provide user, password, host, and port.")

    escaped_user = urllib.parse.quote_plus(user)
    escaped_password = urllib.parse.quote_plus(password)

    mongo_uri = f"mongodb://{escaped_user}:{escaped_password}@{host}:{port}/?authSource={auth_db}"
    
    return MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)