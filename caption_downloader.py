"""
Core logic for downloading YouTube captions using yt-dlp.
"""
import os
import tempfile
import urllib.request
import shutil
from typing import Dict, Optional, List, Any
from dataclasses import dataclass

import yt_dlp

from utils import parse_vtt_to_text, parse_srt_to_text, detect_format


@dataclass
class CaptionResult:
    """Result structure for caption download operations."""
    success: bool
    caption_data: List[Dict[str, Any]]  # List of {'start', 'end', 'text'}
    caption_text: str  # Formatted text for display
    source: Optional[str] = None  # 'manual' or 'auto'
    language: Optional[str] = None
    available_languages: Optional[List[str]] = None
    file_path: Optional[str] = None
    error_message: Optional[str] = None


class CaptionDownloader:
    """Handles downloading and processing YouTube captions."""
    
    def __init__(self):
        self.temp_dir = tempfile.mkdtemp()

    def _select_best_track(self, tracks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Given a list of caption tracks for a single language, pick the one
        in a format we actually know how to parse (VTT/SRT), preferring VTT.

        yt-dlp often exposes multiple formats per language (e.g. json3, vtt);
        previously we just took the first one, which could easily be json3 and
        would then parse to an empty result. That is a root cause of “no output
        even though captions exist”.
        """
        if not tracks:
            return None

        # Prefer formats we can parse natively
        preferred_ext_order = ["vtt", "srt"]

        for ext in preferred_ext_order:
            for track in tracks:
                if track.get("ext") == ext:
                    return track

        # Fallback: return the first track if no preferred format is found
        return tracks[0]
    
    def _extract_base_language_code(self, lang_code: str) -> str:
        """
        Extract base language code from IETF language tag.
        
        Examples:
            'en-US' -> 'en'
            'hi-IN' -> 'hi'
            'zh-Hans' -> 'zh'
            'en' -> 'en'
        
        This is the root cause fix: YouTube uses IETF tags (en-US, hi-IN) but
        users select simple codes (en, hi). We need to match by base code.
        """
        # Split by '-' and take the first part (base language code)
        return lang_code.split('-')[0].lower()
    
    def _find_matching_language(self, requested_lang: str, available_languages: List[str]) -> Optional[str]:
        """
        Find a matching language from available languages using base code matching.
        
        Root cause fix: YouTube uses IETF language tags (en-US, hi-IN) but users
        provide simple codes (en, hi). This method matches by base language code.
        
        Args:
            requested_lang: User-requested language code (e.g., 'en', 'hi')
            available_languages: List of available language codes from YouTube (e.g., ['en-US', 'hi-IN'])
        
        Returns:
            Matching language code from available_languages, or None if no match
        """
        requested_base = self._extract_base_language_code(requested_lang)
        
        # First try exact match
        if requested_lang in available_languages:
            return requested_lang
        
        # Then try base code match
        for available_lang in available_languages:
            available_base = self._extract_base_language_code(available_lang)
            if requested_base == available_base:
                return available_lang
        
        return None
    
    def _extract_language_list(self, metadata: Dict) -> List[str]:
        """Extract list of available languages from metadata."""
        languages = set()
        
        # Check manual subtitles
        subtitles = metadata.get('subtitles', {})
        languages.update(subtitles.keys())
        
        # Check automatic captions
        auto_captions = metadata.get('automatic_captions', {})
        languages.update(auto_captions.keys())
        
        return sorted(list(languages))
    
    def _find_caption_track(self, metadata: Dict, lang: str, prefer_manual: bool = True) -> Optional[Dict]:
        """
        Find the best caption track for the requested language.
        
        Args:
            metadata: Video metadata from yt-dlp
            lang: Requested language code (e.g., 'en', 'hi')
            prefer_manual: If True, prefer manual over auto captions
        
        Returns:
            Dict with 'url', 'ext', and 'source' keys, or None if not found
        """
        subtitles = metadata.get('subtitles', {})
        automatic_captions = metadata.get('automatic_captions', {})
        
        # Handle auto-detect: use first available language
        if lang.lower() in ['auto', 'auto-detect', '']:
            # Try manual first
            if subtitles:
                first_lang = list(subtitles.keys())[0]
                if subtitles[first_lang]:
                    track = self._select_best_track(subtitles[first_lang])
                    return {
                        'url': track.get('url'),
                        'ext': track.get('ext', 'vtt'),
                        'source': 'manual',
                        'language': first_lang
                    }
            # Fall back to auto
            if automatic_captions:
                first_lang = list(automatic_captions.keys())[0]
                if automatic_captions[first_lang]:
                    track = self._select_best_track(automatic_captions[first_lang])
                    return {
                        'url': track.get('url'),
                        'ext': track.get('ext', 'vtt'),
                        'source': 'auto',
                        'language': first_lang
                    }
            return None
        
        # Look for specific language using base code matching
        # Root cause fix: YouTube uses IETF tags (en-US, hi-IN) but users provide simple codes (en, hi)
        manual_track = None
        auto_track = None
        matched_manual_lang = None
        matched_auto_lang = None
        
        # Find matching language in manual subtitles
        manual_languages = list(subtitles.keys())
        matched_manual_lang = self._find_matching_language(lang, manual_languages)
        if matched_manual_lang and subtitles[matched_manual_lang]:
            manual_track = self._select_best_track(subtitles[matched_manual_lang])
        
        # Find matching language in automatic captions
        auto_languages = list(automatic_captions.keys())
        matched_auto_lang = self._find_matching_language(lang, auto_languages)
        if matched_auto_lang and automatic_captions[matched_auto_lang]:
            auto_track = self._select_best_track(automatic_captions[matched_auto_lang])
        
        # Prefer manual if requested
        if prefer_manual and manual_track:
            return {
                'url': manual_track.get('url'),
                'ext': manual_track.get('ext', 'vtt'),
                'source': 'manual',
                'language': matched_manual_lang  # Return the actual matched language code
            }
        elif auto_track:
            return {
                'url': auto_track.get('url'),
                'ext': auto_track.get('ext', 'vtt'),
                'source': 'auto',
                'language': matched_auto_lang  # Return the actual matched language code
            }
        elif manual_track:
            return {
                'url': manual_track.get('url'),
                'ext': manual_track.get('ext', 'vtt'),
                'source': 'manual',
                'language': matched_manual_lang  # Return the actual matched language code
            }
        
        return None
    
    def _download_caption_file(self, url: str, ext: str, ydl: Optional[yt_dlp.YoutubeDL] = None) -> Optional[str]:
        """
        Download caption file from URL.

        Root-level fix: instead of always using bare urllib, prefer yt-dlp's
        own downloader when an instance is available. This way we reuse the
        same headers, cookies, proxies, and other options yt-dlp needs to
        actually access the caption URL, which is often the reason subtitles
        appear in metadata but fail to download.

        Returns:
            Path to downloaded file, or None on failure
        """
        try:
            # Create temporary file
            temp_file = tempfile.NamedTemporaryFile(
                mode='w+b',
                suffix=f'.{ext}',
                delete=False,
                dir=self.temp_dir
            )
            temp_path = temp_file.name
            temp_file.close()

            # Prefer yt-dlp's downloader if provided
            if ydl is not None:
                response = ydl.urlopen(url)
                with open(temp_path, "wb") as out_f:
                    shutil.copyfileobj(response, out_f)
            else:
                # Fallback: basic urllib download
                urllib.request.urlretrieve(url, temp_path)
            
            return temp_path
        except Exception as e:
            return None
    
    def _parse_caption_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Parse caption file (VTT or SRT) into structured data."""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        format_type = detect_format(content)
        
        if format_type == 'vtt':
            return parse_vtt_to_text(content)
        else:
            return parse_srt_to_text(content)
    
    def download_captions(self, url: str, lang: str = 'en') -> CaptionResult:
        """
        Download captions for a YouTube video.
        
        Args:
            url: YouTube video URL
            lang: Language code (e.g., 'en', 'hi') or 'auto' for auto-detect
        
        Returns:
            CaptionResult object with success status and data
        """
        try:
            # Configure yt-dlp to extract metadata only
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
                'writesubtitles': False,
                'writeautomaticsub': False,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # Extract metadata
                metadata = ydl.extract_info(url, download=False)
                
                if not metadata:
                    return CaptionResult(
                        success=False,
                        caption_data=[],
                        caption_text='',
                        error_message="Unable to access this video. It may be private, removed, or restricted."
                    )
                
                # Check if captions exist
                available_languages = self._extract_language_list(metadata)
                
                if not available_languages:
                    return CaptionResult(
                        success=False,
                        caption_data=[],
                        caption_text='',
                        error_message="No captions are available for this video."
                    )
                
                # Find caption track
                caption_track = self._find_caption_track(metadata, lang, prefer_manual=True)
                
                if not caption_track:
                    # Language not available
                    lang_list = ', '.join(available_languages)
                    return CaptionResult(
                        success=False,
                        caption_data=[],
                        caption_text='',
                        available_languages=available_languages,
                        error_message=f"Captions not available in the selected language. Available languages: {lang_list}"
                    )
                
                # Download caption file
                if not caption_track['url']:
                    return CaptionResult(
                        success=False,
                        caption_data=[],
                        caption_text='',
                        error_message="Unable to download caption file."
                    )
                
                file_path = self._download_caption_file(
                    caption_track['url'],
                    caption_track['ext'],
                    ydl=ydl
                )
                
                if not file_path:
                    return CaptionResult(
                        success=False,
                        caption_data=[],
                        caption_text='',
                        error_message="Failed to download caption file. Please try again."
                    )
                
                # Parse caption file
                caption_data = self._parse_caption_file(file_path)
                
                if not caption_data:
                    return CaptionResult(
                        success=False,
                        caption_data=[],
                        caption_text='',
                        error_message="Caption file is empty or could not be parsed."
                    )
                
                # Format for display
                from utils import format_captions_for_display
                caption_text = format_captions_for_display(caption_data)
                
                return CaptionResult(
                    success=True,
                    caption_data=caption_data,
                    caption_text=caption_text,
                    source=caption_track['source'],
                    language=caption_track['language'],
                    file_path=file_path,
                    available_languages=available_languages
                )
        
        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if 'Private video' in error_msg or 'Video unavailable' in error_msg:
                return CaptionResult(
                    success=False,
                    caption_data=[],
                    caption_text='',
                    error_message="Unable to access this video. It may be private, removed, or restricted."
                )
            elif 'Invalid URL' in error_msg or 'not a valid URL' in error_msg:
                return CaptionResult(
                    success=False,
                    caption_data=[],
                    caption_text='',
                    error_message="Please enter a valid YouTube URL (e.g., https://www.youtube.com/watch?v=...)"
                )
            else:
                return CaptionResult(
                    success=False,
                    caption_data=[],
                    caption_text='',
                    error_message=f"Something went wrong: {error_msg}"
                )
        
        except UnicodeDecodeError as e:
            # Root cause fix: Handle encoding errors when reading caption files
            return CaptionResult(
                success=False,
                caption_data=[],
                caption_text='',
                error_message=f"Failed to decode caption file. Encoding error: {str(e)}"
            )
        except ValueError as e:
            # Root cause fix: Handle value errors (e.g., timestamp parsing errors)
            error_msg = str(e)
            if 'timestamp' in error_msg.lower() or 'time' in error_msg.lower():
                return CaptionResult(
                    success=False,
                    caption_data=[],
                    caption_text='',
                    error_message=f"Failed to parse caption timestamps: {error_msg}"
                )
            return CaptionResult(
                success=False,
                caption_data=[],
                caption_text='',
                error_message=f"Invalid data format: {error_msg}"
            )
        except KeyError as e:
            # Root cause fix: Handle missing keys in metadata or caption data
            return CaptionResult(
                success=False,
                caption_data=[],
                caption_text='',
                error_message=f"Missing required data: {str(e)}"
            )
        except Exception as e:
            # Root cause fix: Log the actual exception instead of hiding it
            # This helps identify the real problem instead of showing a generic message
            import traceback
            error_type = type(e).__name__
            error_details = str(e)
            
            # Provide specific error message based on exception type
            if 'Connection' in error_type or 'Timeout' in error_type or 'Network' in error_type:
                error_message = f"Network error: {error_details}. Please check your internet connection."
            elif 'Permission' in error_type or 'Access' in error_type:
                error_message = f"Access denied: {error_details}"
            elif 'FileNotFound' in error_type or 'IOError' in error_type:
                error_message = f"File operation failed: {error_details}"
            else:
                # For unknown errors, show the actual error type and message
                error_message = f"Error ({error_type}): {error_details}"
            
            # Log full traceback for debugging (in production, you might want to log to a file)
            print(f"DEBUG: Full error traceback:\n{traceback.format_exc()}")
            
            return CaptionResult(
                success=False,
                caption_data=[],
                caption_text='',
                error_message=error_message
            )
    
    def cleanup(self):
        """Clean up temporary files."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)
