"""
Utility functions for caption format conversion and parsing.
"""
import re
import json
import html
from typing import List, Dict, Any, Optional

def _timestamp_to_seconds(timestamp: str) -> float:
    """
    Convert timestamp string (HH:MM:SS.mmm) to seconds.
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
        raise ValueError(f"Failed to parse timestamp '{timestamp}': {str(e)}")

def _normalize_text(text: str) -> str:
    """
    Remove speaker markers and normalize spaces.
    """
    text = re.sub(r'(>>\s*)+', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def _is_hypothesis_update(prev: str, curr: str) -> bool:
    """
    Check if the current caption is a simple prefix-based hypothesis update of the previous one.
    e.g., "Hello" -> "Hello world"
    """
    return curr.startswith(prev) and len(curr) > len(prev)

def _collapse_sliding_hypotheses(prev: str, curr: str) -> Optional[str]:
    """
    Detects and collapses "sliding window" ASR hypotheses where the end of the
    previous text overlaps with the beginning of the current one.
    e.g., prev="A B C", curr="B C D" -> returns "B C D"
    """
    prev_words = prev.split()
    curr_words = curr.split()

    max_overlap = min(len(prev_words), len(curr_words))

    # Require a meaningful overlap (>= 3 words) to avoid accidental merges
    for i in range(max_overlap, 2, -1):
        if prev_words[-i:] == curr_words[:i]:
            # The newer hypothesis (curr) replaces the old one
            return curr

    return None

def _reconstruct_utterances(captions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Reconstructs clean, sequential utterances from a stream of raw, overlapping ASR hypotheses.
    This handles both simple prefix updates and complex "sliding window" updates from YouTube's ASR.
    """
    if not captions:
        return []

    # 1. Normalize all caption text first
    normalized_captions = []
    for cap in captions:
        if not isinstance(cap, dict) or not all(k in cap for k in ['start', 'end', 'text']):
            continue
        
        normalized_text = _normalize_text(cap['text'])
        if not normalized_text:
            continue
            
        try:
            start_sec = _timestamp_to_seconds(cap['start'])
            end_sec = _timestamp_to_seconds(cap['end'])
            normalized_captions.append({
                'start': cap['start'],
                'end': cap['end'],
                'text': normalized_text,
                'start_sec': start_sec,
                'end_sec': end_sec
            })
        except ValueError:
            continue
            
    if not normalized_captions:
        return []

    # 2. Reconstruct utterances using replacement logic
    result = []
    buffer = normalized_captions[0].copy()

    for nxt in normalized_captions[1:]:
        prev_text = buffer["text"]
        curr_text = nxt["text"]

        # Check for sliding window overlap first, as it's more complex
        collapsed = _collapse_sliding_hypotheses(prev_text, curr_text)
        
        if collapsed:
            # Utterance is evolving (sliding window) -> replace text & extend time
            buffer["text"] = collapsed
            buffer["end"] = nxt["end"]
            buffer['end_sec'] = nxt['end_sec']
            continue
        
        # Check for simple prefix overlap
        if _is_hypothesis_update(prev_text, curr_text):
            # Utterance is evolving (prefix) -> replace text & extend time
            buffer["text"] = curr_text
            buffer["end"] = nxt["end"]
            buffer['end_sec'] = nxt['end_sec']
            continue

        # If no overlap, the previous utterance is complete. Flush it to the results.
        result.append(buffer)
        buffer = nxt.copy()

    # Flush the last utterance in the buffer
    if buffer:
        result.append(buffer)

    # Convert back to final format, removing temporary keys
    final_captions = [
        {'start': cap['start'], 'end': cap['end'], 'text': cap['text']}
        for cap in result
    ]

    return final_captions


def parse_vtt_to_text(vtt_content: str) -> List[Dict[str, Any]]:
    """
    Parse VTT (WebVTT) format and extract captions with timestamps.
    """
    captions = []
    lines = vtt_content.split('\n')
    current_caption = None

    for line in lines:
        line = line.strip()
        if not line or line.startswith('WEBVTT') or line.startswith('NOTE'):
            continue

        timestamp_pattern = r'(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})'
        match = re.match(timestamp_pattern, line)

        if match:
            if current_caption:
                current_caption['text'] = html.unescape(current_caption['text'])
                current_caption['text'] = re.sub(r'<[^>]+>', '', current_caption['text']).strip()
                if current_caption['text']:
                    captions.append(current_caption)

            start = match.group(1).replace(',', '.')
            end = match.group(2).replace(',', '.')
            current_caption = {'start': start, 'end': end, 'text': ''}
        elif current_caption is not None:
            if re.match(r'^\d{1,6}$', line):
                continue
            if current_caption['text']:
                current_caption['text'] += ' '
            current_caption['text'] += line

    if current_caption and current_caption['text']:
        current_caption['text'] = html.unescape(current_caption['text'])
        current_caption['text'] = re.sub(r'<[^>]+>', '', current_caption['text']).strip()
        captions.append(current_caption)

    try:
        # This is where the reconstruction happens
        return _reconstruct_utterances(captions)
    except Exception as e:
        print(f"Warning: Utterance reconstruction failed, returning original captions: {str(e)}")
        return captions

def parse_srt_to_text(srt_content: str) -> List[Dict[str, Any]]:
    """
    Parse SRT format and extract captions with timestamps.
    """
    captions = []
    blocks = srt_content.strip().split('\n\n')

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue

        timestamp_line = lines[1] if len(lines) > 1 else ''
        timestamp_pattern = r'(\d{2}:\d{2}:\d{2}[\.,]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[\.,]\d{3})'
        match = re.match(timestamp_pattern, timestamp_line)

        if match:
            start = match.group(1).replace(',', '.')
            end = match.group(2).replace(',', '.')
            text = ' '.join(lines[2:]) if len(lines) > 2 else ''
            text = html.unescape(text.strip())
            text = re.sub(r'<[^>]+>', '', text).strip()
            if text:
                captions.append({'start': start, 'end': end, 'text': text})

    try:
        # Also apply reconstruction to SRT as a cleanup step
        return _reconstruct_utterances(captions)
    except Exception as e:
        print(f"Warning: Utterance reconstruction failed, returning original captions: {str(e)}")
        return captions


def format_captions_for_display(caption_data: List[Dict[str, Any]]) -> str:
    """
    Format captions for display in UI with timestamps.
    """
    formatted_lines = []
    for caption in caption_data:
        formatted_lines.append(f"[{caption['start']} --> {caption['end']}]")
        formatted_lines.append(caption['text'])
        formatted_lines.append('')
    return '\n'.join(formatted_lines)


def convert_to_srt(caption_data: List[Dict[str, Any]]) -> str:
    """
    Convert caption data to SRT format.
    """
    srt_lines = []
    for i, caption in enumerate(caption_data, 1):
        start = caption['start'].replace('.', ',')
        end = caption['end'].replace('.', ',')
        srt_lines.append(str(i))
        srt_lines.append(f"{start} --> {end}")
        srt_lines.append(caption['text'])
        srt_lines.append('')
    return '\n'.join(srt_lines)


def convert_to_vtt(caption_data: List[Dict[str, Any]]) -> str:
    """
    Convert caption data to VTT format.
    """
    vtt_lines = ['WEBVTT', '']
    for caption in caption_data:
        start = caption['start']
        end = caption['end']
        vtt_lines.append(f"{start} --> {end}")
        vtt_lines.append(caption['text'])
        vtt_lines.append('')
    return '\n'.join(vtt_lines)


def convert_to_txt(caption_data: List[Dict[str, Any]]) -> str:
    """
    Convert caption data to plain text (no timestamps).
    """
    return '\n'.join([caption['text'] for caption in caption_data])


def convert_to_json(caption_data: List[Dict[str, Any]], source: str, language: str) -> str:
    """
    Convert caption data to JSON structure.
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
    """
    content_lower = content.lower().strip()
    if content_lower.startswith('webvtt'):
        return 'vtt'
    elif re.match(r'^\d+$', content.split('\n')[0].strip()):
        return 'srt'
    else:
        return 'vtt'
