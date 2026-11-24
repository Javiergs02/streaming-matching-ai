# OP_Event_Manager

Event generation service for Amuse Animation's Datamart. Translates external sources (YouTube, Amazon, Broadkast) into standardized domain events and publishes them to MongoDB as the event store.

Hexagonal architecture (ports and adapters). Five independent entry points, one per source/frequency (see `src/run_*.py`), designed to run via `crontab` rather than as a single long-running process.

## Requirements to run

None of this lives in the repository. Everything is injected as an environment variable at deploy time (via GitHub Actions secrets in production, or a local `.env` file for development).

### PostgreSQL connection (Entities & Mapping)
| Variable | Description |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWD` | Connection to the Entities & Mapping database |
| `BK_DB_NAME` | Name of the Broadkast database, reachable with the same credentials above (only this service needs it) |

### MongoDB connection (Event Store)
| Variable | Description |
|---|---|
| `MONGODB_URI`, `MONGODB_DB_NAME` | Connection string and the `PlatformEventsDB` database |
| `MONGODB_WRITER_USER`, `MONGODB_WRITER_PASSWD` | **Write** credentials |
| `MONGODB_CHANNEL_EVENTS_COLLECTION`, `MONGODB_VIDEO_EVENTS_COLLECTION`, `MONGODB_DIFFUSION_EVENTS_COLLECTION`, `MONGODB_ANALYTICS_COLLECTION` | Names of the four destination collections |

### Physical table/column mapping (PostgreSQL)
| Variable | Description |
|---|---|
| `DB_CHANNELS_TABLE`, `DB_VIDEOS_TABLE`, `DB_STATS_TABLE` | Physical tables for channels, videos, and daily statistics |
| `DB_CHANNELS_ID_COLUMN`, `DB_CHANNELS_TITLE_COLUMN`, `DB_CHANNELS_COUNTRY_COLUMN`, `DB_CHANNELS_MONETIZATION_COLUMN` | Columns of the channels table |
| `DB_VIDEOS_ID_COLUMN`, `DB_VIDEOS_CHANNEL_ID_COLUMN`, `DB_VIDEOS_TITLE_COLUMN`, `DB_VIDEOS_DESC_COLUMN`, `DB_VIDEOS_PUBDATE_COLUMN`, `DB_VIDEOS_DURATION_COLUMN`, `DB_VIDEOS_PRIVACY_COLUMN`, `DB_VIDEOS_CAT_COLUMN`, `DB_VIDEOS_TAGS_COLUMN`, `DB_VIDEOS_LANG_COLUMN` | Columns of the videos table |

### External API authentication
| Variable | Description |
|---|---|
| `CREDS_FILE` | YouTube Data/Analytics API credentials (`infrastructure/credentials/youtube_credentials.json`). Supports Google Cloud Service Account JSON keys (recommended) or OAuth 2.0 tokens. |
| `GDRIVE_CREDS_FILE` | Google Service Account JSON, used to read Amazon reports deposited in Google Drive |
| `AMAZON_DRIVE_FOLDER_ID` | Drive folder where Amazon Slate CSVs (SVOD/TVOD) are manually deposited |

### System identification
| Variable | Description |
|---|---|
| `CMS_ID` | Identifier of the Content Owner / CMS (`8_tcxbkqifWJhg_qQZilBg`), included in the metadata envelope of every event and used for `onBehalfOfContentOwner` API calls |

> **Note on YouTube Authentication:** The Google Cloud Service Account (`platforms-data-reader@youtube-api-206312.iam.gserviceaccount.com`, configured via `CREDS_FILE`) must be invited and granted read permissions in the Amuse Animation Content Manager / Content ID (CMS `8_tcxbkqifWJhg_qQZilBg`). Without that permission, `YtVideoEventsService` and `YtAnalyticsEventsService` will fail with 403 Forbidden even if the credentials JSON is syntactically valid.

## Running

Each source has its own entry point, meant to be invoked separately from `crontab` (there is no single "run everything" process):

```bash
python src/run_yt_video_events.py
python src/run_yt_channel_events.py
python src/run_yt_analytics_events.py
python src/run_yt_monthly_territory_events.py
python src/run_diffusion_results_events.py
```

*(Note: Amazon Prime Video ingestion and matching is handled by the unified pipeline in `scripts/run_pipeline.py` and `core/ingestion/`).*

## Deployment

Deployed as a `systemd` service (not Docker), running inside its own Python virtual environment. Deployment is automatic via GitHub Actions (`.github/workflows/deploy.yml`) on every push to `main`: no manual steps required on the server.

## Structure

Hexagonal architecture: `src/domain` (models and ports), `src/application` (use cases, one per source), `src/infrastructure/adapters` (concrete integrations with each API/database).
