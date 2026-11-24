"""Google Drive synchronization module for Amazon Prime Video data.

Allows team members to deposit new or historical Amazon performance and earnings reports
into a shared Google Drive folder, while keeping the local `data/amazon/` repository synchronized.
"""

from __future__ import annotations

import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class GoogleDriveSync:
    """Synchronizes files from a shared Google Drive folder to the local filesystem."""

    def __init__(
        self,
        creds_path: str | Path | None = None,
        folder_id: str | None = None
    ) -> None:
        self.creds_path = Path(creds_path) if creds_path else None
        if not self.creds_path:
            env_creds = os.getenv("GDRIVE_CREDS_FILE") or os.getenv("CREDS_FILE")
            if env_creds:
                self.creds_path = Path(env_creds)

        # Resolve relative creds_path against project root if not found in cwd
        if self.creds_path and not self.creds_path.exists():
            proj_root = Path(__file__).resolve().parent.parent.parent
            candidate = proj_root / self.creds_path
            if candidate.exists():
                self.creds_path = candidate

        self.folder_id = folder_id or os.getenv("AMAZON_DRIVE_FOLDER_ID")
        if self.folder_id:
            self.folder_id = self.folder_id.strip()

        self._service: Any = None

    def is_configured(self) -> bool:
        """Returns True if both credentials file and folder ID are present."""
        return bool(self.creds_path and self.creds_path.exists() and self.folder_id)

    def get_client(self) -> Any:
        """Initializes and returns the authenticated Google Drive API client."""
        if self._service is not None:
            return self._service

        if not self.creds_path or not self.creds_path.exists():
            raise FileNotFoundError(
                f"Google Drive credentials file not found: {self.creds_path}. "
                f"Please define GDRIVE_CREDS_FILE or CREDS_FILE in your environment."
            )

        if not self.folder_id:
            raise ValueError(
                "Google Drive Folder ID not configured. Please define AMAZON_DRIVE_FOLDER_ID in .env."
            )

        with self.creds_path.open("r", encoding="utf-8") as f:
            creds_data = json.load(f)

        from googleapiclient.discovery import build

        # Case 1: Service Account JSON
        if creds_data.get("type") == "service_account":
            from google.oauth2 import service_account
            credentials = service_account.Credentials.from_service_account_info(
                creds_data, scopes=DRIVE_SCOPES
            )
        # Case 2: OAuth 2.0 User Credentials (token, refresh_token, client_id, etc.)
        else:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request
            credentials = Credentials(
                token=creds_data.get("token"),
                refresh_token=creds_data.get("refresh_token"),
                token_uri=creds_data.get("token_uri") or creds_data.get("token_url"),
                client_id=creds_data.get("client_id"),
                client_secret=creds_data.get("client_secret"),
                scopes=creds_data.get("scopes") or DRIVE_SCOPES
            )
            if not credentials.valid and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())

        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def list_folder_contents(
        self,
        folder_id: str | None = None,
        recursive: bool = True
    ) -> List[Dict[str, Any]]:
        """Recursively lists all files and folders under a Google Drive folder."""
        service = self.get_client()
        target_folder = folder_id or self.folder_id

        items_found: List[Dict[str, Any]] = []

        def _traverse(current_folder_id: str, current_path: Path):
            page_token = None
            query = f"'{current_folder_id}' in parents and trashed = false"

            while True:
                response = service.files().list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime)",
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    pageSize=100
                ).execute()

                for f in response.get("files", []):
                    f_name = f.get("name", "")
                    f_mime = f.get("mimeType", "")
                    f_id = f.get("id")
                    item_rel_path = current_path / f_name

                    if f_mime == "application/vnd.google-apps.folder":
                        if recursive:
                            _traverse(f_id, item_rel_path)
                    else:
                        items_found.append({
                            "id": f_id,
                            "name": f_name,
                            "rel_path": str(item_rel_path),
                            "mime_type": f_mime,
                            "size": int(f.get("size", 0) or 0),
                            "modified_time": f.get("modifiedTime")
                        })

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        _traverse(target_folder, Path(""))
        return items_found

    def sync_to_local(
        self,
        local_destination_dir: str | Path = "data/amazon",
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Downloads newly added or updated files from Google Drive to local_destination_dir.

        If a file already exists with identical file size, it is skipped to avoid redundant downloads.
        """
        dest_dir = Path(local_destination_dir)
        dest_dir.mkdir(parents=True, exist_ok=True)

        if not self.is_configured():
            log.info("Google Drive is not configured (missing credentials or folder ID). Using local files.")
            return {
                "status": "skipped_not_configured",
                "downloaded": [],
                "skipped": [],
                "errors": []
            }

        try:
            drive_files = self.list_folder_contents()
        except Exception as e:
            log.error(f"Failed to list Google Drive contents: {e}")
            return {
                "status": "error_listing",
                "error": str(e),
                "downloaded": [],
                "skipped": [],
                "errors": [str(e)]
            }

        service = self.get_client()
        from googleapiclient.http import MediaIoBaseDownload

        downloaded: List[str] = []
        skipped: List[str] = []
        errors: List[str] = []

        for item in drive_files:
            file_id = item["id"]
            rel_path = item["rel_path"]
            drive_size = item["size"]
            
            # Security guard against path traversal (Fix C7)
            local_path = (dest_dir / rel_path).resolve()
            if not local_path.is_relative_to(dest_dir.resolve()):
                err_msg = f"[SECURITY ALERT] Path traversal intentado en Google Drive: {rel_path}"
                log.error(err_msg)
                errors.append(err_msg)
                continue

            # If file already exists and has the same size, skip
            if local_path.exists() and drive_size > 0 and local_path.stat().st_size == drive_size:
                skipped.append(rel_path)
                continue

            if dry_run:
                downloaded.append(f"[DRY-RUN] {rel_path} ({drive_size} bytes)")
                continue

            # Ensure parent directories exist
            local_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = local_path.with_suffix(local_path.suffix + ".tmp")

            try:
                request = service.files().get_media(fileId=file_id)
                with temp_path.open("wb") as fh:
                    downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024 * 2)
                    done = False
                    while not done:
                        status, done = downloader.next_chunk()

                temp_path.replace(local_path)
                downloaded.append(rel_path)
                log.info(f"Downloaded from Drive: {rel_path} -> {local_path}")
            except Exception as e:
                if temp_path.exists():
                    temp_path.unlink()
                err_msg = f"Error downloading {rel_path} (ID: {file_id}): {e}"
                log.error(err_msg)
                errors.append(err_msg)

        return {
            "status": "success",
            "total_drive_files": len(drive_files),
            "downloaded": downloaded,
            "skipped": skipped,
            "errors": errors
        }

