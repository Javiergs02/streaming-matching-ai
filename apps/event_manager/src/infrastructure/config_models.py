from dataclasses import dataclass

@dataclass(frozen=True)
class YT_Credentials:
    token: str
    refresh_token: str
    token_url: str
    client_id: str
    client_secret: str
    scopes: list