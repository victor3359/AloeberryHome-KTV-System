"""Core karaoke engine for managing songs, queue, and playback."""

from __future__ import annotations

import logging
import os
import socket
import subprocess
import time
from typing import Any

import qrcode
from flask_babel import _
from qrcode.image.pure import PyPNGImage

from pikaraoke.lib.download_manager import DownloadManager
from pikaraoke.lib.events import EventSystem
from pikaraoke.lib.favorites import Favorites
from pikaraoke.lib.ffmpeg import (
    get_ffmpeg_version,
    is_transpose_enabled,
    supports_hardware_h264_encoding,
)
from pikaraoke.lib.get_platform import (
    get_data_directory,
    get_os_version,
    get_platform,
    is_raspberry_pi,
)
from pikaraoke.lib.network import get_ip
from pikaraoke.lib.play_stats import PlayStats
from pikaraoke.lib.playback_controller import PlaybackController
from pikaraoke.lib.preference_manager import PreferenceManager
from pikaraoke.lib.queue_manager import QueueManager
from pikaraoke.lib.song_manager import SongManager
from pikaraoke.lib.vocal_separator import VocalSeparator
from pikaraoke.lib.youtube_dl import (
    get_search_results,
    get_youtubedl_version,
    upgrade_youtubedl,
)
from pikaraoke.version import __version__ as VERSION


class Karaoke:
    """Main karaoke engine managing songs, queue, and playback.

    This class handles all core karaoke functionality including:
    - Song queue management
    - YouTube video downloading
    - Playback coordination via PlaybackController
    - User preferences
    - QR code generation

    Attributes:
        available_songs: List of available song file paths.
        queue_manager: Queue management for songs.
        playback_controller: Playback state and stream coordination.
        volume: Current volume level (0.0 to 1.0).
    """

    song_manager: SongManager
    queue_manager: QueueManager
    playback_controller: PlaybackController

    now_playing_notification: str | None = None
    volume: float

    qr_code_path: str | None = None
    base_path: str = os.path.dirname(__file__)
    loop_interval: int = 500  # in milliseconds
    default_logo_path: str = os.path.join(base_path, "static", "images", "logo.png")
    default_bg_music_path: str = os.path.join(base_path, "static", "music")
    default_bg_video_path: str = os.path.join(base_path, "static", "video", "night_sea.mp4")
    screensaver_timeout: int

    normalize_audio: bool
    show_splash_clock: bool

    # Download manager for serialized downloads
    download_manager: DownloadManager

    # Event system and preferences
    events: EventSystem
    preferences: PreferenceManager

    def __init__(
        self,
        # Non-preference parameters (keep their own defaults)
        additional_ytdl_args: str | None = None,
        bg_music_path: str | None = None,
        bg_video_path: str | None = None,
        config_file_path: str = "config.ini",
        download_path: str = "/usr/lib/pikaraoke/songs",
        hide_splash_screen: bool | None = None,
        log_level: int = logging.DEBUG,
        logo_path: str | None = None,
        port: int = 5555,
        prefer_hostname: bool | None = None,
        preferred_language: str | None = None,
        socketio=None,
        streaming_format: str = "hls",
        url: str | None = None,
        youtubedl_proxy: str | None = None,
        # Preference parameters (defaults from PreferenceManager.DEFAULTS)
        avsync: float | None = None,
        bg_music_volume: float | None = None,
        browse_results_per_page: int | None = None,
        buffer_size: int | None = None,
        cdg_pixel_scaling: bool | None = None,
        complete_transcode_before_play: bool | None = None,
        disable_bg_music: bool | None = None,
        disable_bg_video: bool | None = None,
        disable_score: bool | None = None,
        hide_notifications: bool | None = None,
        hide_overlay: bool | None = None,
        hide_url: bool | None = None,
        high_quality: bool | None = None,
        limit_user_songs_by: int | None = None,
        normalize_audio: bool | None = None,
        screensaver_timeout: int | None = None,
        show_splash_clock: bool | None = None,
        splash_delay: int | None = None,
        volume: float | None = None,
    ) -> None:
        """Initialize the Karaoke instance.

        Args:
            port: HTTP server port number.
            download_path: Directory path for downloaded songs.
            hide_url: Hide URL and QR code on splash screen.
            hide_notifications: Disable notification popups.
            hide_splash_screen: Run in headless mode.
            high_quality: Download higher quality videos (up to 1080p).
            volume: Default volume level (0.0 to 1.0).
            normalize_audio: Apply loudness normalization.
            complete_transcode_before_play: Buffer entire file before playback.
            buffer_size: Transcode buffer size in KB.
            log_level: Logging level (e.g., logging.DEBUG).
            splash_delay: Seconds to wait between songs.
            youtubedl_proxy: Proxy URL for yt-dlp.
            logo_path: Custom logo image path.
            hide_overlay: Hide video overlay.
            screensaver_timeout: Screensaver activation delay in seconds.
            url: Override auto-detected URL.
            prefer_hostname: Use hostname instead of IP in URL.
            disable_bg_music: Disable background music.
            bg_music_volume: Background music volume (0.0 to 1.0).
            bg_music_path: Directory for background music files.
            bg_video_path: Path to background video file.
            disable_bg_video: Disable background video.
            disable_score: Disable score screen.
            limit_user_songs_by: Max songs per user in queue (0 = unlimited).
            avsync: Audio/video sync adjustment in seconds.
            config_file_path: Path to config.ini file.
            cdg_pixel_scaling: Enable CDG pixel scaling.
            streaming_format: Video streaming format ('hls' or 'mp4').
            browse_results_per_page: Number of search results per page.
            additional_ytdl_args: Additional yt-dlp command arguments.
            socketio: SocketIO instance for real-time event emission.
            preferred_language: Language code for UI (e.g., 'en', 'de_DE').
        """
        logging.basicConfig(
            format="[%(asctime)s] %(levelname)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            level=int(log_level),
        )

        # Initialize event system and preferences (foundation for all components)
        self.events = EventSystem()
        self.preferences = PreferenceManager(config_file_path, target=self)

        # Platform-specific initializations
        self.platform = get_platform()
        self.os_version = get_os_version()
        self.ffmpeg_version = get_ffmpeg_version()
        self.is_transpose_enabled = is_transpose_enabled()
        self.supports_hardware_h264_encoding = supports_hardware_h264_encoding()
        self.youtubedl_version = get_youtubedl_version()
        self.is_raspberry_pi = is_raspberry_pi()

        logging.info("PiKaraoke version: " + VERSION)

        # Set non-preference attributes (not stored in config)
        self.port = port
        self.hide_splash_screen = hide_splash_screen
        self.download_path = download_path
        self.log_level = log_level
        self.youtubedl_proxy = youtubedl_proxy
        self.additional_ytdl_args = additional_ytdl_args
        self.logo_path = self.default_logo_path if logo_path is None else logo_path
        self.prefer_hostname = prefer_hostname
        self.bg_music_path = self.default_bg_music_path if bg_music_path is None else bg_music_path
        self.bg_video_path = self.default_bg_video_path if bg_video_path is None else bg_video_path
        self.streaming_format = streaming_format
        self.socketio = socketio
        self.url_override = url
        self.url = self.get_url()

        # Load all preference-driven attributes from config (with CLI overrides as fallback)
        cli_args = {k: v for k, v in locals().items() if k != "self"}
        self._load_preferences(**cli_args)

        # Log the settings to debug level
        self.log_settings_to_debug()

        # Initialize song manager and load songs from download_path
        self.song_manager = SongManager(self.download_path)
        self.song_manager.refresh_songs()

        self.generate_qr_code()

        # Set preferred language from command line if provided (persists to config)
        if preferred_language:
            self.preferences.set("preferred_language", preferred_language)
            logging.info(f"Setting preferred language to: {preferred_language}")

        # Initialize playback controller for video playback and FFmpeg coordination
        self.playback_controller = PlaybackController(
            preferences=self.preferences,
            events=self.events,
            filename_from_path=SongManager.filename_from_path,
            streaming_format=self.streaming_format,
        )

        # Event bridging: the coordinator wires manager events to the UI (SocketIO/notifications).
        self.events.on("notification", self.log_and_send)
        self.events.on(
            "queue_update",
            lambda: self.socketio.emit("queue_update", namespace="/") if self.socketio else None,
        )
        self.events.on("now_playing_update", self.update_now_playing_socket)
        self.events.on("playback_started", self.update_now_playing_socket)
        self.events.on("song_ended", self.update_now_playing_socket)
        self.events.on("skip_requested", lambda: self.playback_controller.skip(False))

        # Session score history: list of {singer, score, song}
        self.score_history: list[dict] = []
        # Singers who have queued a song this session
        self.known_singers: set[str] = set()
        # Session start time (unix timestamp) for elapsed display
        self.session_start: float = time.time()
        # Play history this session: list of {title, user, user2}
        self.play_history: list[dict] = []

        # Persistent cross-session data
        data_dir = get_data_directory()
        self.play_stats = PlayStats(data_dir)
        self.favorites = Favorites(data_dir)

        # Initialize queue manager
        self.queue_manager = QueueManager(
            preferences=self.preferences,
            events=self.events,
            get_now_playing_user=lambda: self.playback_controller.now_playing_user,
            filename_from_path=SongManager.filename_from_path,
            get_available_songs=lambda: self.song_manager.songs,
        )

        # Initialize and start download manager
        # Initialize vocal separator (optional, requires demucs/whisper)
        self.vocal_separator = VocalSeparator(
            events=self.events,
            download_path=self.download_path,
        )

        self.download_manager = DownloadManager(
            events=self.events,
            preferences=self.preferences,
            song_manager=self.song_manager,
            queue_manager=self.queue_manager,
            download_path=self.download_path,
            youtubedl_proxy=self.youtubedl_proxy,
            additional_ytdl_args=self.additional_ytdl_args,
            vocal_separator=self.vocal_separator if self.vocal_separator.is_available() else None,
        )
        self.download_manager.start()

    def _load_preferences(self, **cli_overrides: Any) -> None:
        """Load preference-driven attributes from config file.

        Priority: CLI argument (if provided) > config file > PreferenceManager.DEFAULTS
        """
        self.preferences.apply_all(**cli_overrides)

    def change_audio_mode(self, audio_mode: str) -> None:
        """Restart the current song with a different audio mode (original/instrumental/guide)."""
        filename = self.playback_controller.now_playing_filename
        user = self.playback_controller.now_playing_user
        semitones = self.playback_controller.now_playing_transpose

        if filename is None or user is None:
            logging.warning("Cannot change audio mode: no song currently playing")
            return

        mode_labels = {"original": "Original", "instrumental": "Karaoke", "guide": "Guide Vocal"}
        label = mode_labels.get(audio_mode, audio_mode)
        self.log_and_send(_("Audio: %s") % label)
        self.queue_manager.enqueue(filename, user, semitones, True, audio_mode=audio_mode)
        self.playback_controller.skip(log_action=False)

    def reset_session(self) -> None:
        """Reset all session state for a new KTV session."""
        self.queue_manager.queue_clear()
        self.score_history.clear()
        self.play_history.clear()
        self.known_singers.clear()
        self.session_start = time.time()
        logging.info("Session reset")

    def get_session_summary(self) -> dict:
        """Compute summary statistics for the current session."""
        elapsed = int(time.time() - self.session_start)
        total_songs = len(self.play_history)
        singers = list(self.known_singers)

        # Most active singer
        singer_counts: dict[str, int] = {}
        for entry in self.play_history:
            u = entry.get("user", "")
            if u:
                singer_counts[u] = singer_counts.get(u, 0) + 1
        most_active = max(singer_counts, key=singer_counts.get) if singer_counts else None

        # Top scorer
        top_scorer = None
        if self.score_history:
            by_singer: dict[str, list[int]] = {}
            for entry in self.score_history:
                by_singer.setdefault(entry["singer"], []).append(entry["score"])
            avgs = {s: sum(scores) / len(scores) for s, scores in by_singer.items()}
            top_scorer = max(avgs, key=avgs.get) if avgs else None

        # Most played song this session
        song_counts: dict[str, int] = {}
        for entry in self.play_history:
            t = entry.get("title", "")
            if t:
                song_counts[t] = song_counts.get(t, 0) + 1
        most_played = max(song_counts, key=song_counts.get) if song_counts else None

        return {
            "elapsed_seconds": elapsed,
            "total_songs": total_songs,
            "total_singers": len(singers),
            "singers": singers,
            "most_active_singer": most_active,
            "top_scorer": top_scorer,
            "most_played_song": most_played,
        }

    def get_url(self):
        """Get the URL for accessing the PiKaraoke web interface.

        On Raspberry Pi, retries getting the IP address for up to 30 seconds
        in case the network is still initializing at startup.

        Returns:
            URL string in format http://ip:port
        """
        if self.is_raspberry_pi:
            # retry in case pi is still starting up
            # and doesn't have an IP yet (occurs when launched from /etc/rc.local)
            end_time = int(time.time()) + 30
            while int(time.time()) < end_time:
                addresses_str = (
                    subprocess.check_output(["hostname", "-I"]).strip().decode("utf-8", "ignore")
                )
                addresses = addresses_str.split(" ")
                self.ip = addresses[0]
                if len(self.ip) < 7:
                    logging.debug("Couldn't get IP, retrying....")
                else:
                    break
        else:
            self.ip = get_ip(self.platform)

        logging.debug("IP address (for QR code and splash screen): " + self.ip)

        if self.url_override != None:
            logging.debug("Overriding URL with " + self.url_override)
            url = self.url_override
        else:
            if self.prefer_hostname:
                url = f"http://{socket.getfqdn().lower()}:{self.port}"
            else:
                url = f"http://{self.ip}:{self.port}"
        return url

    def log_settings_to_debug(self) -> None:
        """Log all current settings at debug level."""
        output = ""
        for key, value in sorted(vars(self).items()):
            output += f"  {key}: {value}\n"
        logging.debug("\n\n" + output)

    def generate_qr_code(self) -> None:
        """Generate a QR code image for the web interface URL."""
        logging.debug("Generating URL QR code")
        qr = qrcode.QRCode(
            version=1,
            box_size=1,
            border=4,
        )
        qr.add_data(self.url)
        qr.make()
        img = qr.make_image(image_factory=PyPNGImage)
        # Use writable data directory instead of program directory
        data_dir = get_data_directory()
        self.qr_code_path = os.path.join(data_dir, "qrcode.png")
        img.save(self.qr_code_path)  # type: ignore[arg-type]

    def send_notification(self, message: str, color: str = "primary") -> None:
        """Send a notification to the web interface.

        Args:
            message: Notification message text.
            color: Bulma color class (primary, warning, success, danger).
        """
        # Color should be bulma compatible: primary, warning, success, danger
        hide_notifications = self.preferences.get_or_default("hide_notifications")
        if not hide_notifications:
            # don't allow new messages to clobber existing commands, one message at a time
            # other commands have a higher priority
            if self.now_playing_notification != None:
                return
            self.now_playing_notification = message + "::is-" + color
            # Emit notification via SocketIO for event-driven architecture
            if self.socketio:
                self.socketio.emit("notification", self.now_playing_notification, namespace="/")

    def log_and_send(self, message: str, category: str = "info") -> None:
        """Log a message and send it as a notification.

        Args:
            message: Message to log and display.
            category: Message category (info, success, warning, danger).
        """
        # Category should be one of: info, success, warning, danger
        if category == "success":
            logging.info(message)
            self.send_notification(message, "success")
        elif category == "warning":
            logging.warning(message)
            self.send_notification(message, "warning")
        elif category == "danger":
            logging.error(message)
            self.send_notification(message, "danger")
        else:
            logging.info(message)
            self.send_notification(message, "primary")

    def transpose_current(self, semitones: int) -> None:
        """Restart the current song with a new transpose value.

        Args:
            semitones: Number of semitones to transpose.
        """
        filename = self.playback_controller.now_playing_filename
        user = self.playback_controller.now_playing_user
        now_playing = self.playback_controller.now_playing

        if filename is None or user is None:
            logging.warning("Cannot transpose: no song currently playing")
            return
        # MSG: Message shown after the song is transposed, first is the semitones and then the song name
        self.log_and_send(_("Transposing by %s semitones: %s") % (semitones, now_playing))
        # Insert the same song at the top of the queue with transposition
        self.queue_manager.enqueue(filename, user, semitones, True)
        self.playback_controller.skip(log_action=False)

    def volume_change(self, vol_level: float) -> bool:
        """Set the volume level.

        Args:
            vol_level: Volume level (0.0 to 1.0).

        Returns:
            True after setting volume.
        """
        self.volume = vol_level
        # MSG: Message shown after the volume is changed, will be followed by the volume level
        self.log_and_send(_("Volume: %s") % (int(self.volume * 100)))
        self.update_now_playing_socket()
        return True

    def vol_up(self) -> None:
        """Increase volume by 10%."""
        new_vol = min(self.volume + 0.1, 1.0)
        self.volume_change(new_vol)
        logging.debug(f"Increasing volume by 10%: {self.volume}")

    def vol_down(self) -> None:
        """Decrease volume by 10%."""
        new_vol = max(self.volume - 0.1, 0.0)
        self.volume_change(new_vol)
        logging.debug(f"Decreasing volume by 10%: {self.volume}")

    def restart(self) -> bool:
        """Restart the current song from the beginning.

        Returns:
            True if successful, False if nothing playing.
        """
        if self.playback_controller.is_playing:
            now_playing = self.playback_controller.now_playing
            logging.info("Restarting: " + (now_playing or "unknown song"))
            self.playback_controller.is_paused = False
            self.update_now_playing_socket()
            return True
        else:
            logging.warning("Tried to restart, but no file is playing!")
            return False

    def stop(self) -> None:
        """Stop the karaoke run loop."""
        self.running = False

    def handle_run_loop(self) -> None:
        """Handle one iteration of the main run loop with a sleep interval."""
        time.sleep(self.loop_interval / 1000)

    def reset_now_playing_notification(self) -> None:
        """Clear the current notification."""
        self.now_playing_notification = None

    def reset_now_playing(self) -> None:
        """Reset all now playing state to defaults."""
        self.playback_controller.reset_now_playing()
        self.volume = self.preferences.get_or_default("volume")
        self.update_now_playing_socket()

    def get_now_playing(self) -> dict[str, Any]:
        """Get the current playback state.

        Returns:
            Dictionary with now playing info, queue preview, and volume.
        """
        queue = self.queue_manager.queue
        next_song = queue[0] if queue else None

        # Get playback state from PlaybackController
        playback_state = self.playback_controller.get_now_playing()

        # Check if stems exist for the current song
        has_stems = False
        filename = self.playback_controller.now_playing_filename
        if filename:
            has_stems = self.vocal_separator.has_stems(filename)

        return {
            **playback_state,
            "up_next": next_song["title"] if next_song else None,
            "next_user": next_song["user"] if next_song else None,
            "next_user2": next_song.get("user2") if next_song else None,
            "volume": self.volume,
            "session_elapsed": int(time.time() - self.session_start),
            "has_stems": has_stems,
        }

    def update_now_playing_socket(self) -> None:
        """Emit now_playing state change via SocketIO."""
        if self.socketio:
            self.socketio.emit("now_playing", self.get_now_playing(), namespace="/")

    def run(self) -> None:
        """Main run loop - processes queue and plays songs.

        This method blocks until stop() is called or KeyboardInterrupt.
        """
        logging.debug("Starting PiKaraoke run loop")
        logging.info(f"Connect the player host to: {self.url}/splash")
        self.running = True
        while self.running:
            try:
                # Clean up if playback ended but state wasn't reset
                if (
                    not self.playback_controller.is_playing
                    and self.playback_controller.now_playing is not None
                ):
                    self.reset_now_playing()

                # Auto-DJ: add a random song when queue is empty and not playing
                if (
                    len(self.queue_manager.queue) == 0
                    and self.auto_dj
                    and not self.playback_controller.is_playing
                    and self.playback_controller.now_playing is None
                ):
                    self.queue_manager.queue_add_random(1)

                # Start next song from queue if not currently playing
                if len(self.queue_manager.queue) > 0 and not self.playback_controller.is_playing:
                    self.reset_now_playing()
                    # Splash delay between songs
                    splash_delay = self.preferences.get_or_default("splash_delay")
                    i = 0
                    while i < (splash_delay * 1000):
                        self.handle_run_loop()
                        i += self.loop_interval

                    # Pop song before playback to avoid UI flicker
                    song = self.queue_manager.pop_next()
                    if not song:
                        continue
                    song_title = song.get("title", "")
                    self.play_history.append(
                        {
                            "title": song_title,
                            "user": song.get("user", ""),
                            "user2": song.get("user2"),
                        }
                    )
                    if song_title:
                        self.play_stats.increment(song_title)
                    result = self.playback_controller.play_file(
                        song["file"],
                        song["user"],
                        song["semitones"],
                        song.get("user2"),
                        song.get("audio_mode", "original"),
                    )

                    if not result.success and result.error:
                        self.log_and_send(result.error, "danger")

                self.playback_controller.log_output()
                self.handle_run_loop()
            except KeyboardInterrupt:
                logging.warning("Keyboard interrupt: Exiting pikaraoke...")
                self.running = False
