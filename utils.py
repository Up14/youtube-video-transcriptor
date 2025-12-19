"""
Utility functions for caption format conversion and parsing.
"""
import re
import json
import html
from typing import List, Dict, Any


def parse_vtt_to_text(vtt_content: str) -> List[Dict[str, Any]]:
    """
    Parse VTT (WebVTT) format and extract captions with timestamps.
    
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
            if current_caption:
                # Decode HTML entities and strip WebVTT specific tags before adding caption
                current_caption['text'] = html.unescape(current_caption['text'])
                current_caption['text'] = re.sub(r'<[^>]+>', '', current_caption['text']).strip()
                captions.append(current_caption)
            
            start = match.group(1).replace(',', '.')
            end = match.group(2).replace(',', '.')
            current_caption = {
                'start': start,
                'end': end,
                'text': ''
            }
        elif current_caption and line:
            # Accumulate text lines
            if current_caption['text']:
                current_caption['text'] += ' '
            current_caption['text'] += line
    
    # Add last caption
    if current_caption:
        # Decode HTML entities and strip WebVTT specific tags before adding caption
        current_caption['text'] = html.unescape(current_caption['text'])
        current_caption['text'] = re.sub(r'<[^>]+>', '', current_caption['text']).strip()
        captions.append(current_caption)
    
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
