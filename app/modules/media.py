"""Media file operations - listing, disk usage, allowed extensions."""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from . import config

log = logging.getLogger(__name__)

_pillow_warned = False


def get_allowed_extensions():
    """Get the set of allowed file extensions."""
    image_ext = [
        e.strip()
        for e in config.get(
            "IMAGE_EXTENSIONS", ".jpg,.jpeg,.png,.bmp,.gif,.webp,.tiff"
        ).split(",")
    ]
    video_ext = [
        e.strip()
        for e in config.get(
            "VIDEO_EXTENSIONS", ".mp4,.mkv,.avi,.mov,.webm,.m4v,.mpg,.mpeg"
        ).split(",")
    ]
    return set(image_ext), set(video_ext)


def get_media_dir():
    """Get the media directory path."""
    return config.get("MEDIA_DIR", "/home/pi/media")


def allowed_file(filename):
    """Check if a filename has an allowed extension."""
    image_ext, video_ext = get_allowed_extensions()
    ext = Path(filename).suffix.lower()
    return ext in (image_ext | video_ext)


def is_video(filename):
    """Check if a filename is a video."""
    _, video_ext = get_allowed_extensions()
    return Path(filename).suffix.lower() in video_ext


def format_size(size_bytes):
    """Format bytes to human readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024:
            if unit == "B":
                return f"{int(size_bytes)} {unit}"
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def get_media_files():
    """Get all media files sorted by modification time (newest first)."""
    media_path = Path(get_media_dir())
    if not media_path.exists():
        return []

    image_ext, video_ext = get_allowed_extensions()
    all_ext = image_ext | video_ext
    files = []

    # Skip the thumbnails and quarantine subdirectories, and .tmp files
    thumbnails_dir = media_path / "thumbnails"
    quarantine_dir = media_path / "quarantine"
    skip_dirs = {thumbnails_dir, quarantine_dir}
    for f in media_path.rglob("*"):
        if f.is_file() and f.suffix.lower() in all_ext and not any(d in f.parents for d in skip_dirs) and not f.name.endswith(".tmp"):
            stat = f.stat()
            files.append(
                {
                    "name": f.name,
                    "path": str(f.relative_to(media_path)),
                    "size": stat.st_size,
                    "size_human": format_size(stat.st_size),
                    "modified": stat.st_mtime,
                    "is_video": f.suffix.lower() in video_ext,
                    "ext": f.suffix.lower(),
                }
            )

    files.sort(key=lambda x: x["modified"], reverse=True)
    return files


def get_disk_usage():
    """Get disk usage stats for the media directory."""
    media_dir = get_media_dir()
    if not Path(media_dir).exists():
        return {"total": "N/A", "used": "N/A", "free": "N/A", "percent": 0, "free_bytes": 0}
    total, used, free = shutil.disk_usage(media_dir)
    return {
        "total": format_size(total),
        "used": format_size(used),
        "free": format_size(free),
        "free_bytes": free,
        "percent": round(used / total * 100, 1),
    }


def cleanup_orphan_thumbnails():
    """Remove thumbnails that no longer have a corresponding media file.

    This handles the case where media files are deleted outside the web UI
    (e.g., via SSH, file manager, or USB). Called periodically to prevent
    thumbnail accumulation over months of operation.
    """
    media_dir = Path(get_media_dir())
    thumb_dir = media_dir / "thumbnails"
    if not thumb_dir.exists():
        return 0

    _, video_ext = get_allowed_extensions()
    # Build a set of stems for all current video files (including subdirectories)
    video_stems = set()
    for f in media_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in video_ext:
            video_stems.add(f.stem)

    removed = 0
    for thumb in thumb_dir.iterdir():
        if thumb.is_file() and thumb.suffix.lower() == ".jpg":
            if thumb.stem not in video_stems:
                try:
                    thumb.unlink()
                    removed += 1
                except OSError as exc:
                    log.warning("Failed to remove orphan thumbnail %s: %s", thumb, exc)
    return removed


def extract_gps(image_path):
    """Extract GPS coordinates as (lat, lon) or None from EXIF.

    Uses Pillow's getexif() and get_ifd(ExifTags.IFD.GPSInfo) to read
    GPS data, then converts DMS (degrees/minutes/seconds) to decimal
    degrees. Returns None if no GPS data is present or if the file
    cannot be read.

    Args:
        image_path: Path to the image file (str or Path).

    Returns:
        A tuple of (latitude, longitude) as floats, or None.
    """
    global _pillow_warned
    try:
        from PIL import Image as PILImage
        from PIL import ExifTags
    except ImportError:
        if not _pillow_warned:
            log.warning("Pillow not installed — GPS extraction disabled")
            _pillow_warned = True
        return None

    try:
        with PILImage.open(str(image_path)) as img:
            exif_data = img.getexif()
            if not exif_data:
                return None

            gps_ifd = exif_data.get_ifd(ExifTags.IFD.GPSInfo)
            if not gps_ifd:
                return None

            # GPSLatitude = tag 2, GPSLatitudeRef = tag 1
            # GPSLongitude = tag 4, GPSLongitudeRef = tag 3
            gps_lat = gps_ifd.get(2)
            gps_lat_ref = gps_ifd.get(1)
            gps_lon = gps_ifd.get(4)
            gps_lon_ref = gps_ifd.get(3)

            if not gps_lat or not gps_lon or not gps_lat_ref or not gps_lon_ref:
                return None

            def dms_to_decimal(dms, ref):
                """Convert DMS tuple (degrees, minutes, seconds) to decimal."""
                degrees = float(dms[0])
                minutes = float(dms[1])
                seconds = float(dms[2])
                decimal = degrees + minutes / 60.0 + seconds / 3600.0
                if ref in ("S", "W"):
                    decimal = -decimal
                return round(decimal, 6)

            lat = dms_to_decimal(gps_lat, gps_lat_ref)
            lon = dms_to_decimal(gps_lon, gps_lon_ref)

            return (lat, lon)
    except Exception:
        log.warning("GPS extraction failed for %s", image_path, exc_info=True)
        return None


def _locations_cache_path():
    """Return the path to the locations cache file."""
    return Path(get_media_dir()) / ".locations.json"


def _load_locations_cache():
    """Load the locations cache from disk.

    Returns:
        A dict mapping filename to {"lat": float, "lon": float}, or
        an empty dict if the cache does not exist or is corrupt.
    """
    cache_path = _locations_cache_path()
    if not cache_path.exists():
        return {}
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_locations_cache(cache):
    """Atomically write the locations cache to disk.

    Uses a temporary file and rename to avoid corruption on power loss.

    Args:
        cache: Dict mapping filename to {"lat": float, "lon": float}.
    """
    cache_path = _locations_cache_path()
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=str(cache_path.parent), suffix=".tmp"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(cache, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            Path(tmp_path).replace(cache_path)
        except Exception:
            # Clean up temp file on failure
            try:
                Path(tmp_path).unlink()
            except OSError:
                pass
            raise
    except Exception as exc:
        log.warning("Failed to save locations cache: %s", exc)


def get_photo_locations():
    """Get GPS locations for all photos, using a JSON cache file.

    Scans all image files in MEDIA_DIR. Only extracts GPS for files not
    already present in the cache. Removes cache entries for files that
    no longer exist on disk. Returns a list of dicts with name, lat, lon.

    Returns:
        A list of dicts: [{"name": str, "lat": float, "lon": float}, ...]
        Returns an empty list if Pillow is not available.
    """
    global _pillow_warned
    try:
        from PIL import Image as PILImage  # noqa: F401
    except ImportError:
        if not _pillow_warned:
            log.warning("Pillow not installed — photo location scanning disabled")
            _pillow_warned = True
        return []

    media_path = Path(get_media_dir())
    if not media_path.exists():
        return []

    image_ext, _ = get_allowed_extensions()
    thumbnails_dir = media_path / "thumbnails"

    # Collect current image filenames
    current_images = set()
    for f in media_path.rglob("*"):
        if (
            f.is_file()
            and f.suffix.lower() in image_ext
            and thumbnails_dir not in f.parents
        ):
            current_images.add(f.name)

    cache = _load_locations_cache()
    dirty = False

    # Remove entries for deleted files
    stale_keys = set(cache.keys()) - current_images
    if stale_keys:
        for key in stale_keys:
            del cache[key]
        dirty = True

    # Extract GPS for new files (not yet in cache)
    new_files = current_images - set(cache.keys())
    for name in new_files:
        filepath = media_path / name
        coords = extract_gps(filepath)
        # Store in cache even if None (as empty dict) so we don't re-scan
        if coords:
            cache[name] = {"lat": coords[0], "lon": coords[1]}
        else:
            cache[name] = {}
        dirty = True

    if dirty:
        _save_locations_cache(cache)

    # Build result list (only entries with actual coordinates)
    return [
        {"name": name, "lat": data["lat"], "lon": data["lon"]}
        for name, data in cache.items()
        if data.get("lat") is not None and data.get("lon") is not None
    ]


def update_location_cache(filename, coords):
    """Update the locations cache for a single file.

    Args:
        filename: The filename (not path) of the image.
        coords: A tuple (lat, lon) or None.
    """
    cache = _load_locations_cache()
    if coords:
        cache[filename] = {"lat": coords[0], "lon": coords[1]}
    else:
        cache[filename] = {}
    _save_locations_cache(cache)


def remove_from_location_cache(filename):
    """Remove a file from the locations cache.

    Args:
        filename: The filename (not path) to remove.
    """
    cache = _load_locations_cache()
    if filename in cache:
        del cache[filename]
        _save_locations_cache(cache)
