from domain.ports import ChannelFetcher
from domain.models import Channel

class YoutubeChannelFetcher(ChannelFetcher):
    def __init__(self, youtube_client, cms_id: str):
        self.client = youtube_client
        self.cms_id = cms_id.strip()

    def fetch_all(self) -> list[Channel]:
        channels = []
        next_page_token = None
        
        while True:
            try:
                request = self.client.channels().list(
                    part="snippet,contentOwnerDetails",
                    managedByMe=True,
                    onBehalfOfContentOwner=self.cms_id,
                    maxResults=50,
                    pageToken=next_page_token
                )
                response = request.execute()
            except Exception as e:
                print(f"[ERROR] API fetch failed for channels: {e}")
                raise 
            
            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                co_details = item.get('contentOwnerDetails', {})
                
                youtube_extras = {
                    "is_monetization_enabled": co_details.get('isMonetized', False),
                    "raw_metadata": item 
                }
                
                channels.append(Channel(
                    channel_id=item['id'],
                    platform="youtube",
                    title=snippet.get('title', ''),
                    description=snippet.get('description', ''),
                    country_code=snippet.get('country', ''),
                    extra_data=youtube_extras
                ))
                
            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break
            
        return channels