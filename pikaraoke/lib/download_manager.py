"""Download queue manager for serialized video downloads."""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import uuid
from queue import Queue
from threading import Thread
from typing import Any

from pikaraoke.lib.events import EventSystem
from pikaraoke.lib.preference_manager import PreferenceManager
from pikaraoke.lib.queue_manager import QueueManager
from pikaraoke.lib.song_manager import SongManager
from pikaraoke.lib.youtube_dl import (
    build_ytdl_download_command,
    get_youtube_id_from_url,
)


class DownloadManager:
    """Manages a queue of video downloads, processing them serially.

    This prevents rate limiting from download sources and reduces CPU load
    by ensuring only one download runs at a time.

    Attributes:
        download_queue: Queue holding pending download requests.
    """

    def __init__(
        self,
        events: EventSystem,
        preferences: PreferenceManager,
        song_manager: SongManager,
        queue_manager: QueueManager,
        download_path: str,
        youtubedl_proxy: str | None = None,
        additional_ytdl_args: str | None = None,
        vocal_separator: Any = None,
        song_db: Any = None,
    ) -> None:
        """Initialize the download manager.

        Args:
            events: Event system for notifications and broadcasts.
            preferences: Configuration manager for persistent settings.
            song_manager: Manager for song library operations.
            queue_manager: Manager for playback queue.
            download_path: Directory where downloads are saved.
            youtubedl_proxy: Optional proxy URL for yt-dlp.
            additional_ytdl_args: Optional additional arguments for yt-dlp.
        """
        self._events = events
        self._preferences = preferences
        self._song_manager = song_manager
        self._queue_manager = queue_manager
        self._vocal_separator = vocal_separator
        self._song_db = song_db
        self._download_path = download_path
        self._youtubedl_proxy = youtubedl_proxy
        self._additional_ytdl_args = additional_ytdl_args
        self.download_queue: Queue = Queue()
        self._state_lock = threading.RLock()
        self.pending_downloads: list[dict] = []  # Shadow queue for visibility
        self.download_errors: list[dict] = []  # Track failed downloads
        self.active_download: dict | None = None
        self._worker_thread: Thread | None = None
        self._is_downloading: bool = False  # Track if a download is currently in progress

    def start(self) -> None:
        """Start the download worker thread."""
        self._worker_thread = Thread(target=self._process_queue, daemon=True)
        self._worker_thread.start()
        logging.debug("Download queue worker started")

    def get_downloads_status(self) -> dict:
        """Get the status of active and pending downloads.

        Returns:
            Dict containing 'active' download info and list of 'pending' downloads.
        """
        with self._state_lock:
            return {
                "active": self.active_download,
                "pending": list(self.pending_downloads),
                "errors": list(self.download_errors),
            }

    def remove_error(self, error_id: str) -> bool:
        """Remove an error from the list by ID.

        Args:
            error_id: The ID of the error to remove.

        Returns:
            True if removed, False if not found.
        """
        with self._state_lock:
            initial_len = len(self.download_errors)
            self.download_errors = [e for e in self.download_errors if e["id"] != error_id]
            return len(self.download_errors) < initial_len

    def queue_download(
        self,
        video_url: str,
        enqueue: bool = False,
        user: str = "Pikaraoke",
        title: str | None = None,
    ) -> None:
        """Queue a video for download.

        Downloads are processed serially to prevent rate limiting and CPU overload.

        Args:
            video_url: YouTube video URL.
            enqueue: Whether to add to playback queue after download.
            user: Username to attribute the download to.
            title: Display title (defaults to URL if not provided).
        """
        from flask_babel import _

        # Strip playlist parameter to avoid downloading entire playlists
        if "&list=" in video_url:
            video_url = video_url.split("&list=")[0]

        displayed_title = title if title else video_url

        # Check how many items are ahead (in queue + currently downloading)
        pending_count = self.download_queue.qsize() + (1 if self._is_downloading else 0)

        if pending_count > 0:
            # MSG: Message shown when download is added to queue (not first in line)
            self._events.emit(
                "notification",
                _("Download queued (#%d): %s") % (pending_count + 1, displayed_title),
            )
        else:
            # MSG: Message shown when download is added and will start immediately
            self._events.emit("notification", _("Download starting: %s") % displayed_title)

        # If queue was just started (was not downloading before), emit event
        if not self._is_downloading and self.download_queue.empty():
            self._events.emit("download_started")

        download_data = {
            "video_url": video_url,
            "enqueue": enqueue,
            "user": user,
            "title": title,
            "display_title": displayed_title,
        }

        # Add to the download queue and shadow list
        self.download_queue.put(download_data)
        self.pending_downloads.append(download_data)

    def _process_queue(self) -> None:
        """Worker thread that processes downloads from the queue serially.

        Runs indefinitely, blocking on queue.get() until items are available.
        Each download is processed completely before the next one starts.
        """
        while True:
            download_request = self.download_queue.get()

            # Remove from shadow queue
            # Note: Since this is a single worker thread and append happens on main thread,
            # we simply pop the first item as it corresponds to FIFO queue.
            # In a multi-worker scenario, this would need a lock.
            if self.pending_downloads:
                self.pending_downloads.pop(0)

            self._is_downloading = True

            # Initialize active download state
            self.active_download = {
                "title": download_request.get("display_title", download_request["video_url"]),
                "url": download_request["video_url"],
                "user": download_request["user"],
                "progress": 0.0,
                "status": "starting",
                "eta": "--:--",
                "speed": "---",
            }

            try:
                self._execute_download(
                    download_request["video_url"],
                    download_request["enqueue"],
                    download_request["user"],
                    download_request["title"],
                )
            except Exception as e:
                logging.error(f"Error processing download: {e}")
            finally:
                self._is_downloading = False
                self.active_download = None
                self.download_queue.task_done()

                # Check if we are done with all downloads
                if self.download_queue.empty():
                    self._events.emit("download_stopped")

    def _execute_download(
        self,
        video_url: str,
        enqueue: bool,
        user: str,
        title: str | None,
    ) -> int:
        """Execute a video download.

        Args:
            video_url: YouTube video URL.
            enqueue: Whether to add to queue after download.
            user: Username to attribute the download to.
            title: Display title (defaults to URL if not provided).

        Returns:
            Return code from the download process (0 = success).
        """
        from flask_babel import _

        displayed_title = title if title else video_url

        # MSG: Message shown when download actually starts (after waiting in queue)
        self._events.emit("notification", _("Downloading video: %s") % displayed_title)

        cmd = build_ytdl_download_command(
            video_url,
            self._download_path,
            self._preferences.get_or_default("high_quality"),
            self._youtubedl_proxy,
            self._additional_ytdl_args,
        )
        logging.debug("Youtube-dl command: " + " ".join(cmd))

        # Use Popen to capture output in real-time
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
            universal_newlines=True,
        )

        output_buffer = []

        # Regex to parse progress from yt-dlp stdout
        # Example: [download]   0.0% of    4.62MiB at  396.66KiB/s ETA 00:12
        progress_regex = re.compile(
            r"\[download\]\s+(\d+\.?\d*)%\s+of\s+.*?\s+at\s+([^\s]+)\s+ETA\s+([^\s]+)"
        )
        video_id = get_youtube_id_from_url(video_url)

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            if line:
                output_buffer.append(line)
                match = progress_regex.search(line)
                if match and self.active_download:
                    percent = float(match.group(1))
                    speed = match.group(2)
                    eta = match.group(3)

                    self.active_download["progress"] = percent
                    self.active_download["status"] = "downloading"
                    self.active_download["speed"] = speed
                    self.active_download["eta"] = eta
                # Log only non-progress lines to avoid spamming logs, or log everything at debug
                # logging.debug(line.strip())

        rc = process.poll()
        output = "".join(output_buffer)

        if rc != 0:
            # Logic removed: We no longer retry synchronously as it blocks the queue.
            # Failed downloads are now failed fast and logged.

            # MSG: Message shown after the download process is completed but the song is not found
            self._events.emit(
                "notification", _("Error downloading song: ") + displayed_title, "danger"
            )
            logging.error(f"yt-dlp stderr: {output}")
            self.download_errors.append(
                {
                    "id": str(uuid.uuid4()),
                    "title": displayed_title,
                    "url": video_url,
                    "user": user,
                    "error": output or "Unknown error",
                }
            )
        else:
            if self.active_download:
                self.active_download["progress"] = 100
                self.active_download["status"] = "complete"

            # MSG: Message shown after the download is completed
            self._events.emit("notification", _("已下載：%s") % displayed_title, "success")

            # After download, find the file path by ID
            song_path = None
            if video_id:
                logging.debug(f"Searching for downloaded file by ID: {video_id}")
                song_path = self._song_manager.songs.find_by_id(self._download_path, video_id)
            else:
                logging.warning("No video ID available to find downloaded song")

            song_is_valid = False
            if song_path:
                song_is_valid = self._song_manager.songs.add_if_valid(song_path)
            else:
                logging.warning(
                    f"Could not find downloaded song in {self._download_path} matching ID: {video_id}"
                )

            # Post-download: run vocal separation + transcription BEFORE queueing
            if song_is_valid and song_path and self._vocal_separator:
                self._events.emit("notification", _("正在處理音訊：%s") % displayed_title, "info")
                try:
                    self._vocal_separator.process(song_path, title=displayed_title)
                except Exception as e:
                    logging.warning("Vocal processing failed for %s: %s", song_path, e)

            # Auto-normalize song name: "YouTubeTitle" → "Artist - Song"
            if song_is_valid and song_path:
                # Extract YouTube ID BEFORE renaming (rename removes it from filename)
                import re as _re

                _yt_match = _re.search(r"---([A-Za-z0-9_-]{11})\.", os.path.basename(song_path))
                _youtube_id = _yt_match.group(1) if _yt_match else (video_id or "")

                try:
                    from pikaraoke.lib.metadata_parser import regex_tidy

                    display_name = self._song_manager.filename_from_path(song_path)
                    corrected = regex_tidy(display_name)
                    if (
                        corrected
                        and corrected != display_name
                        and " - " in corrected
                        and len(corrected) > 3
                    ):
                        self._song_manager.rename(song_path, corrected)
                        ext = os.path.splitext(song_path)[1]
                        song_path = os.path.join(self._download_path, corrected + ext)
                        logging.info("Auto-renamed: %s → %s", display_name, corrected)
                except Exception as e:
                    logging.warning("Auto-rename failed: %s", e)

                # Update song database with YouTube ID and thumbnail (even after rename)
                try:
                    from pikaraoke.routes.files import _detect_language

                    clean_name = self._song_manager.filename_from_path(song_path, True)
                    parts = clean_name.split(" - ", 1)
                    artist = parts[0].strip() if len(parts) > 1 else ""
                    title = parts[1].strip() if len(parts) > 1 else clean_name
                    thumb = (
                        f"https://img.youtube.com/vi/{_youtube_id}/mqdefault.jpg"
                        if _youtube_id
                        else ""
                    )
                    stem_base = os.path.splitext(song_path)[0]
                    self._song_db.upsert_song(
                        song_path,
                        artist=artist,
                        title=title,
                        language=_detect_language(clean_name),
                        youtube_id=_youtube_id,
                        thumbnail_url=thumb,
                        has_stems=int(os.path.exists(stem_base + "_instrumental.mp3")),
                        has_lyrics=int(os.path.exists(stem_base + "_karaoke.ass")),
                    )
                except Exception as e:
                    logging.warning("DB update failed: %s", e)

            if enqueue:
                if song_is_valid and song_path:
                    self._queue_manager.enqueue(song_path, user, log_action=False)
                else:
                    # MSG: Message shown after the download is completed but the adding to queue fails
                    self._events.emit(
                        "notification", _("Error queueing song: ") + displayed_title, "danger"
                    )

        return rc
