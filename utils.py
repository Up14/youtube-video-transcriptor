"""
Utility functions for caption format conversion and parsing.
"""
import re
import json
import html
from typing import List, Dict, Any


def _timestamp_to_seconds(timestamp: str) -> float:
    """
    Convert timestamp string (HH:MM:SS.mmm) to seconds.
    
    Root cause fix: Added error handling for malformed timestamps to prevent crashes.
    """
    try:
        parts = timestamp.split(':')
        if len(parts) != 3:
            raise ValueError(f"Invalid timestamp format: {timestamp}. Expected HH:MM:SS.mmm")
        
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds_parts = parts[2].split('.')
        if len(seconds_parts) == 0:
            raise ValueError(f"Invalid timestamp format: {timestamp}. Missing seconds")
        
        seconds = int(seconds_parts[0])
        milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except (ValueError, IndexError) as e:
        # If timestamp parsing fails, raise a more descriptive error
        raise ValueError(f"Failed to parse timestamp '{timestamp}': {str(e)}")


def _deduplicate_overlapping_captions(captions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove duplicate and overlapping captions from auto-generated VTT files.
    
    Root cause fix: YouTube's auto-generated captions contain overlapping segments
    where each caption builds incrementally (e.g., "Text A", "Text A", "Text A Text B").
    This function merges overlapping captions and removes redundant duplicates.
    
    Strategy:
    1. Convert timestamps to seconds for easier comparison
    2. Sort captions by start time, then by text length (longer first)
    3. For overlapping/duplicate captions, keep the longest/most complete version
    4. Remove exact duplicates and very short redundant segments
    """
    if not captions:
        return captions
    
    # Convert timestamps to seconds and add to caption dicts for processing
    processed = []
    for cap in captions:
        # Root cause fix: Validate caption structure before processing
        if not isinstance(cap, dict):
            continue
        
        # Check for required keys
        if 'start' not in cap or 'end' not in cap or 'text' not in cap:
            continue
        
        text = cap['text'].strip()
        if not text:  # Skip empty captions
            continue
        
        try:
            start_sec = _timestamp_to_seconds(cap['start'])
            end_sec = _timestamp_to_seconds(cap['end'])
        except (ValueError, KeyError) as e:
            # Skip captions with invalid timestamps
            continue
        
        processed.append({
            'start': cap['start'],
            'end': cap['end'],
            'text': text,
            'start_sec': start_sec,
            'end_sec': end_sec,
            'duration': end_sec - start_sec
        })
    
    # Sort by start time, then by text length (longer first for same start time)
    processed.sort(key=lambda x: (x['start_sec'], -len(x['text'])))
    
    deduplicated = []
    
    for current in processed:
        should_add = True
        
        # Normalize text for comparison (remove extra spaces)
        current_text_norm = ' '.join(current['text'].split())
        
        # Check against all previously added captions
        for i, prev in enumerate(deduplicated):
            # Calculate time overlap and adjacency
            overlap_start = max(current['start_sec'], prev['start_sec'])
            overlap_end = min(current['end_sec'], prev['end_sec'])
            has_overlap = overlap_end > overlap_start
            
            # Check if captions are adjacent (one ends exactly when the next starts)
            # This is common in YouTube auto-generated captions
            is_adjacent = (abs(current['start_sec'] - prev['end_sec']) < 0.01 or 
                          abs(prev['start_sec'] - current['end_sec']) < 0.01)
            
            # Check if they're close in time (within 0.5 seconds)
            time_gap = min(abs(current['start_sec'] - prev['end_sec']),
                          abs(prev['start_sec'] - current['end_sec']))
            is_close = time_gap < 0.5
            
            prev_text_norm = ' '.join(prev['text'].split())
            
            # Case 1: Exact duplicate (same text and overlapping/adjacent time)
            if current_text_norm == prev_text_norm and (has_overlap or is_adjacent):
                should_add = False
                break
            
            # Case 2: Current is a subset of previous
            # Root cause fix: Also check adjacent/close captions, not just overlapping ones
            if current_text_norm in prev_text_norm:
                # If they overlap, are adjacent, or current is very short, prefer the longer one
                if has_overlap or is_adjacent or current['duration'] < 0.2:
                    should_add = False
                    break
            
            # Case 3: Previous is a subset of current (current is more complete)
            if prev_text_norm in current_text_norm:
                # Replace previous with current if they overlap, are adjacent, or prev is very short
                prev_duration = prev.get('duration', prev['end_sec'] - prev['start_sec'])
                if has_overlap or is_adjacent or prev_duration < 0.2:
                    deduplicated[i] = {
                        'start': current['start'],
                        'end': current['end'],
                        'text': current['text'],
                        'start_sec': current['start_sec'],
                        'end_sec': current['end_sec']
                    }
                    should_add = False
                    break
            
            # Case 4: Very short duration captions that are subsets or duplicates
            # Root cause fix: Remove very short redundant segments even without strict overlap
            if current['duration'] < 0.15:  # Less than 150ms
                # Check if it's a duplicate or subset of any nearby caption
                if (current_text_norm == prev_text_norm or 
                    current_text_norm in prev_text_norm or
                    prev_text_norm in current_text_norm):
                    if is_close:  # Within 0.5 seconds
                        should_add = False
                        break
            
            # Case 5: Check if current text starts with previous text (incremental building)
            # This handles cases like "Text A" followed by "Text A Text B"
            if prev_text_norm and current_text_norm.startswith(prev_text_norm):
                # If they're adjacent or overlapping, prefer the longer one
                if is_adjacent or has_overlap:
                    # Replace previous with current (more complete)
                    deduplicated[i] = {
                        'start': current['start'],
                        'end': current['end'],
                        'text': current['text'],
                        'start_sec': current['start_sec'],
                        'end_sec': current['end_sec'],
                        'duration': current['duration']
                    }
                    should_add = False
                    break
            
            # Case 6: Check if current text ends with previous text (tail overlap)
            # This handles cases where a short caption repeats the end of previous
            if prev_text_norm and current_text_norm.endswith(prev_text_norm):
                # If current is shorter and they're adjacent/overlapping, skip current
                if len(current_text_norm) < len(prev_text_norm) and (is_adjacent or has_overlap):
                    should_add = False
                    break
        
        if should_add:
            # Root cause fix: Keep start_sec, end_sec, and duration for comparison purposes
            deduplicated.append({
                'start': current['start'],
                'end': current['end'],
                'text': current['text'],
                'start_sec': current['start_sec'],
                'end_sec': current['end_sec'],
                'duration': current['duration']
            })
    
    # Final pass: sort by start time for output
    deduplicated.sort(key=lambda x: x['start_sec'])
    
    # Remove temporary fields before returning (only keep start, end, text)
    result = []
    for cap in deduplicated:
        result.append({
            'start': cap['start'],
            'end': cap['end'],
            'text': cap['text']
        })
    
    return result


def parse_vtt_to_text(vtt_content: str) -> List[Dict[str, Any]]:
    """
    Parse VTT (WebVTT) format and extract captions with timestamps.
    
    Root cause fix: VTT files can have optional cue identifiers (often just numbers)
    that appear on their own line before timestamps. These were being incorrectly
    included as text content. The fix properly detects and skips cue identifiers.
    
    WebVTT structure:
    - Optional cue identifier (standalone line, no '-->')
    - Timestamp line (required, contains '-->')
    - Text lines (caption content)
    - Empty line separator
    
    Returns:
        List of dicts with keys: 'start', 'end', 'text'
    """
    captions = []
    lines = vtt_content.split('\n')
    
    current_caption = None
    
    for line in lines:
        line = line.strip()
        
        # Skip empty lines and metadata
        if not line or line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue
        
        # Match timestamp line: 00:00:00.000 --> 00:00:05.000
        timestamp_pattern = r'(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})'
        match = re.match(timestamp_pattern, line)
        
        if match:
            # Found timestamp - finish previous caption if exists
            if current_caption:
                # Decode HTML entities and strip WebVTT specific tags before adding caption
                current_caption['text'] = html.unescape(current_caption['text'])
                current_caption['text'] = re.sub(r'<[^>]+>', '', current_caption['text']).strip()
                captions.append(current_caption)
            
            # Start new caption
            start = match.group(1).replace(',', '.')
            end = match.group(2).replace(',', '.')
            current_caption = {
                'start': start,
                'end': end,
                'text': ''
            }
        elif current_caption:
            # We have an active caption, so this could be text content OR a cue identifier
            # Root cause fix: Cue identifiers can appear AFTER text content in VTT files.
            # They're typically standalone numbers (like "2", "3") on their own line.
            # We need to detect and skip them to prevent adding them to caption text.
            
            # Check if this line is likely a cue identifier (just digits, standalone)
            # Cue identifiers are typically short numeric sequences (1-6 digits) that appear
            # between caption text and the next timestamp. Real caption text with numbers
            # would typically be part of a sentence on the same line, not standalone digits.
            if re.match(r'^\d{1,6}$', line):
                # This looks like a cue identifier - skip it
                # The next non-empty line should be a timestamp for the next caption
                continue
            
            # This is actual text content - add it to the caption
            if current_caption['text']:
                current_caption['text'] += ' '
            current_caption['text'] += line
        else:
            # No active caption - this could be a cue identifier
            # Root cause fix: Cue identifiers (often just numbers like "2", "3") appear
            # on their own line before timestamps. They don't contain '-->' and should
            # be skipped, not treated as text content.
            # Skip lines that look like cue identifiers (digits only, or short identifiers)
            if '-->' not in line:
                # Check if it looks like a cue identifier
                if re.match(r'^\d+$', line) or (len(line) < 100 and not re.search(r'[.!?,\s]', line)):
                    # This is a cue identifier, skip it
                    continue
            # If it's not a timestamp and not a cue identifier, skip it (malformed VTT)
    
    # Add last caption
    if current_caption:
        current_caption['text'] = html.unescape(current_caption['text'])
        current_caption['text'] = re.sub(r'<[^>]+>', '', current_caption['text']).strip()
        captions.append(current_caption)
    
    # Root cause fix: Deduplicate overlapping captions from auto-generated VTT files
    # YouTube's auto-generated captions contain overlapping segments that need to be merged
    try:
        return _deduplicate_overlapping_captions(captions)
    except Exception as e:
        # If deduplication fails, return original captions rather than crashing
        # This ensures the app still works even if deduplication encounters an issue
        print(f"Warning: Deduplication failed, returning original captions: {str(e)}")
        return captions


def parse_srt_to_text(srt_content: str) -> List[Dict[str, Any]]:
    """
    Parse SRT format and extract captions with timestamps.
    
    Returns:
        List of dicts with keys: 'start', 'end', 'text'
    """
    captions = []
    blocks = srt_content.strip().split('\n\n')
    
    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue
        
        # Skip sequence number (first line)
        timestamp_line = lines[1] if len(lines) > 1 else ''
        
        # Match timestamp: 00:00:00,000 --> 00:00:05,000
        timestamp_pattern = r'(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})'
        match = re.match(timestamp_pattern, timestamp_line)
        
        if match:
            start = match.group(1).replace(',', '.')
            end = match.group(2).replace(',', '.')
            text = ' '.join(lines[2:]) if len(lines) > 2 else ''
            
            # Decode HTML entities and strip any HTML-like tags (e.g., &nbsp; -> regular space, <c> -> '')
            text = html.unescape(text.strip())
            text = re.sub(r'<[^>]+>', '', text).strip()
            
            captions.append({
                'start': start,
                'end': end,
                'text': text
            })
    
    # Root cause fix: Deduplicate overlapping captions (though SRT files typically don't have this issue)
    try:
        return _deduplicate_overlapping_captions(captions)
    except Exception as e:
        # If deduplication fails, return original captions rather than crashing
        print(f"Warning: Deduplication failed, returning original captions: {str(e)}")
        return captions


def format_captions_for_display(caption_data: List[Dict[str, Any]]) -> str:
    """
    Format captions for display in UI with timestamps.
    
    Format:
    [00:00:00.000 --> 00:00:05.000]
    Caption text here
    
    Returns:
        Formatted string for display
    """
    formatted_lines = []
    for caption in caption_data:
        formatted_lines.append(f"[{caption['start']} --> {caption['end']}]")
        formatted_lines.append(caption['text'])
        formatted_lines.append('')  # Empty line between captions
    
    return '\n'.join(formatted_lines)


def convert_to_srt(caption_data: List[Dict[str, Any]]) -> str:
    """
    Convert caption data to SRT format.
    
    Returns:
        SRT formatted string
    """
    srt_lines = []
    for i, caption in enumerate(caption_data, 1):
        start = caption['start'].replace('.', ',')
        end = caption['end'].replace('.', ',')
        srt_lines.append(str(i))
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(caption['text'])
        srt_lines.append('')  # Empty line between blocks
    
    return '\n'.join(srt_lines)


def convert_to_vtt(caption_data: List[Dict[str, Any]]) -> str:
    """
    Convert caption data to VTT format.
    
    Returns:
        VTT formatted string
    """
    vtt_lines = ['WEBVTT', '']
    for caption in caption_data:
        start = caption['start']
        end = caption['end']
        vtt_lines.append(f"{start} --> {end}")
        vtt_lines.append(caption['text'])
        vtt_lines.append('')  # Empty line between blocks
    
    return '\n'.join(vtt_lines)


def convert_to_txt(caption_data: List[Dict[str, Any]]) -> str:
    """
    Convert caption data to plain text (no timestamps).
    
    Returns:
        Plain text string
    """
    return '\n'.join([caption['text'] for caption in caption_data])


def convert_to_json(caption_data: List[Dict[str, Any]], source: str, language: str) -> str:
    """
    Convert caption data to JSON structure.
    
    Returns:
        JSON formatted string
    """
    result = {
        'source': source,
        'language': language,
        'caption_count': len(caption_data),
        'captions': caption_data
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


def detect_format(content: str) -> str:
    """
    Detect caption format (VTT or SRT) from content.
    
    Returns:
        'vtt' or 'srt'
    """
    content_lower = content.lower().strip()
    if content_lower.startswith('webvtt'):
        return 'vtt'
    elif re.match(r'^\d+$', content.split('\n')[0].strip()):
        return 'srt'
    else:
        # Default to VTT if uncertain (most common format from YouTube)
        return 'vtt'
