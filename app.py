"""
YouTube Caption Downloader - Streamlit App
"""
import streamlit as st
from caption_downloader import CaptionDownloader, CaptionResult
from utils import (
    convert_to_srt,
    convert_to_vtt,
    convert_to_txt,
    convert_to_json
)

# Page configuration
st.set_page_config(
    page_title="YouTube Caption Downloader",
    page_icon="📝",
    layout="centered"
)

# Initialize session state
if 'downloader' not in st.session_state:
    st.session_state.downloader = CaptionDownloader()

if 'last_result' not in st.session_state:
    st.session_state.last_result = None

if 'last_url' not in st.session_state:
    st.session_state.last_url = ''

if 'last_lang' not in st.session_state:
    st.session_state.last_lang = 'en'

# Language options
LANGUAGE_OPTIONS = {
    'Auto-detect': 'auto',
    'English': 'en',
    'Hindi': 'hi',
    'Spanish': 'es',
    'French': 'fr',
    'German': 'de',
    'Italian': 'it',
    'Portuguese': 'pt',
    'Japanese': 'ja',
    'Korean': 'ko',
    'Chinese': 'zh',
    'Russian': 'ru',
    'Arabic': 'ar',
    'Turkish': 'tr',
    'Dutch': 'nl',
    'Polish': 'pl',
}

# UI Header
st.title("📝 YouTube Caption Downloader")
st.markdown("Download captions from YouTube videos. Supports both manual and auto-generated captions.")

# Input Section
st.header("Video Information")

url = st.text_input(
    "YouTube URL",
    value=st.session_state.last_url,
    placeholder="https://www.youtube.com/watch?v=...",
    help="Enter the full YouTube video URL"
)

# Language selection
lang_display = st.selectbox(
    "Language",
    options=list(LANGUAGE_OPTIONS.keys()),
    index=list(LANGUAGE_OPTIONS.values()).index(st.session_state.last_lang) if st.session_state.last_lang in LANGUAGE_OPTIONS.values() else 1,
    help="Select the language for captions. 'Auto-detect' will use the first available language."
)

lang_code = LANGUAGE_OPTIONS[lang_display]

# Download button
download_button = st.button("Download Captions", type="primary", use_container_width=True)

# Process request
if download_button:
    if not url or not url.strip():
        st.error("❌ Please enter a valid YouTube URL (e.g., https://www.youtube.com/watch?v=...)")
    elif 'youtube.com' not in url and 'youtu.be' not in url:
        st.error("❌ Please enter a valid YouTube URL (e.g., https://www.youtube.com/watch?v=...)")
    else:
        with st.spinner("Downloading captions..."):
            result = st.session_state.downloader.download_captions(url.strip(), lang_code)
            st.session_state.last_result = result
            st.session_state.last_url = url.strip()
            st.session_state.last_lang = lang_code

# Display results
if st.session_state.last_result:
    result = st.session_state.last_result
    
    if result.success:
        st.success(f"✅ Captions downloaded successfully! (Source: {result.source}, Language: {result.language})")
        
        # Caption display section
        st.header("Captions")
        st.text_area(
            "Caption Text",
            value=result.caption_text,
            height=400,
            disabled=True,
            label_visibility="collapsed"
        )
        
        # Download buttons section
        st.header("Download")
        st.markdown("Download captions in your preferred format:")
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            srt_content = convert_to_srt(result.caption_data)
            st.download_button(
                label="📄 Download SRT",
                data=srt_content,
                file_name=f"captions_{result.language}.srt",
                mime="text/plain",
                use_container_width=True
            )
        
        with col2:
            vtt_content = convert_to_vtt(result.caption_data)
            st.download_button(
                label="📄 Download VTT",
                data=vtt_content,
                file_name=f"captions_{result.language}.vtt",
                mime="text/vtt",
                use_container_width=True
            )
        
        with col3:
            txt_content = convert_to_txt(result.caption_data)
            st.download_button(
                label="📄 Download TXT",
                data=txt_content,
                file_name=f"captions_{result.language}.txt",
                mime="text/plain",
                use_container_width=True
            )
        
        with col4:
            json_content = convert_to_json(result.caption_data, result.source, result.language)
            st.download_button(
                label="📄 Download JSON",
                data=json_content,
                file_name=f"captions_{result.language}.json",
                mime="application/json",
                use_container_width=True
            )
    
    else:
        # Error message
        st.error(f"❌ {result.error_message}")
        
        # Show available languages if language-specific error
        if result.available_languages:
            st.info(f"💡 Available languages for this video: {', '.join(result.available_languages)}")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "Enter a YouTube URL and select a language to download captions"
    "</div>",
    unsafe_allow_html=True
)

# Cleanup on app close (optional, for better resource management)
import atexit
atexit.register(st.session_state.downloader.cleanup)