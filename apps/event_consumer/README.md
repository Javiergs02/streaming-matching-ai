# OP_Event_Consumer

Consumption service for Amuse Animation's Datamart. Reads unprocessed events from the MongoDB event store and projects their content onto the Entities & Mapping database in PostgreSQL, resolving structural integrity (project, series, episode) before inserting the final mapping.

Hexagonal architecture. Unlike the Manager, it exposes a single entry point (`main.py`) that sequentially chains the consumption of all collections in one scheduled run: channels first, then videos, and finally diffusions (in that order, due to the real dependency between structural data and the mapping).

## Requirements to run

Everything is injected as an environment variable at deploy time.

### PostgreSQL connection (Entities & Mapping)
| Variable | Description |
|---|---|
| `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWD` | Connection to the Entities & Mapping database (projection target) |

> This service does **not** need `BK_DB_NAME`: it never queries Broadkast directly, it only processes what the Manager has already published as an event.

### MongoDB connection (Event Store)
| Variable | Description |
|---|---|
| `MONGODB_URI`, `MONGODB_DB_NAME` | Connection string and the `PlatformEventsDB` database |
| `MONGODB_WRITER_USER`, `MONGODB_WRITER_PASSWD` | Write credentials (needed to mark events as processed after projecting them) |
| `MONGODB_CHANNEL_EVENTS_COLLECTION`, `MONGODB_VIDEO_EVENTS_COLLECTION`, `MONGODB_DIFFUSION_EVENTS_COLLECTION` | Collections this service consumes. `MONGODB_ANALYTICS_COLLECTION` does not apply here: performance events don't require structural integrity resolution and never go through this Consumer |

## Running

```bash
python main.py
```

Single, sequential run: there are no independent entry points per event type.

## Deployment

Deployed as a `systemd` service (not Docker), running inside its own Python virtual environment. Automatic deployment via GitHub Actions on every push to `main`.

## Retries and reprocessing

The system is idempotent: re-running `main.py` over already-processed events does not duplicate or corrupt data (`upsert` operations in PostgreSQL, explicit marking of consumed events in MongoDB). If a run is interrupted midway, simply relaunch it — it automatically resumes from the events that were left unmarked as processed.

## Structure

Hexagonal architecture: `domain/`, `application/`, `infrastructure/adapters/`. Unlike `OP_Event_Manager`, it has no independent `run_*.py` per event type: all orchestration lives in `main.py`.
