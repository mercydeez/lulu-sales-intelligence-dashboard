"""
Deepgram Voice Service - Enhanced Speech-to-Text and Text-to-Speech
Real-time voice transcription with improved accuracy and noise handling
"""
import os
import json
import asyncio
import re
from typing import Optional, AsyncGenerator
import httpx
import base64

# Get API key from environment
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
DEEPGRAM_STT_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"

# Sales-specific vocabulary for better recognition
SALES_VOCABULARY = [
    "Lulu", "hypermarket", "sales", "revenue", "profit", "margin",
    "store", "item", "category", "beverages", "dairy", "frozen",
    "vegetables", "personal care", "household", "snacks", "bakery",
    "Karama", "Barsha", "Deira", "Ajman", "Sharjah", "Fujairah",
    "Abu Dhabi", "Ras Al Khaimah", "Dubai", "UAE",
    "KPI", "analytics", "trend", "forecast", "prediction",
    "dashboard", "chart", "graph", "performance", "comparison",
    "today", "yesterday", "weekly", "monthly", "annual",
    "return", "refund", "bulk", "promotional", "discount"
]


class DeepgramService:
    """Enhanced Deepgram service for STT and TTS with improved accuracy"""
    
    def __init__(self):
        self.api_key = DEEPGRAM_API_KEY
        self.vocabulary_boost = SALES_VOCABULARY
    
    def _get_headers(self) -> dict:
        return {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def _clean_transcription(self, text: str) -> str:
        """Clean and improve transcription output"""
        if not text:
            return ""
        
        # Capitalize first letter
        text = text.strip()
        if text:
            text = text[0].upper() + text[1:]
        
        # Fix common misrecognitions in sales context
        replacements = {
            r'\blulu\b': 'Lulu',
            r'\bkarama\b': 'Karama',
            r'\bbarsha\b': 'Barsha',
            r'\bdeira\b': 'Deira',
            r'\bajman\b': 'Ajman',
            r'\bsharjah\b': 'Sharjah',
            r'\bfujairah\b': 'Fujairah',
            r'\bkpi\b': 'KPI',
            r'\bkpis\b': 'KPIs',
            r'\buae\b': 'UAE',
            r'\bras al khaimah\b': 'Ras Al Khaimah',
            r'\babu dhabi\b': 'Abu Dhabi',
            # Common speech-to-text errors
            r'\bsells\b': 'sales',
            r'\bcells\b': 'sales',
            r'\bsale\b(?!\s)': 'sales',
            r'\bstores\s+sales\b': "store's sales",
            r'\btodays\b': "today's",
            r'\byesterdays\b': "yesterday's",
        }
        
        for pattern, replacement in replacements.items():
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        
        # Ensure proper ending punctuation
        if text and text[-1] not in '.?!':
            if any(q in text.lower() for q in ['what', 'how', 'why', 'when', 'where', 'which', 'who', 'can you', 'could you', 'show me']):
                text += '?'
            else:
                text += '.'
        
        return text
    
    async def transcribe_audio(
        self,
        audio_data: bytes,
        mimetype: str = "audio/webm",
        language: str = "en",
        smart_format: bool = True,
        punctuate: bool = True,
        detect_language: bool = False
    ) -> dict:
        """
        Transcribe audio to text using Deepgram STT with enhanced settings
        
        Args:
            audio_data: Raw audio bytes
            mimetype: Audio MIME type
            language: Language code (e.g., 'en', 'ar')
            smart_format: Apply smart formatting
            punctuate: Add punctuation
            detect_language: Auto-detect language
        
        Returns:
            Transcription result with text and metadata
        """
        if not self.api_key:
            return {"error": "Deepgram API key not configured", "text": ""}
        
        # Enhanced query parameters for better accuracy
        params = {
            "model": "nova-2",           # Latest model with better accuracy
            "smart_format": str(smart_format).lower(),
            "punctuate": str(punctuate).lower(),
            "diarize": "false",           # Single speaker
            "profanity_filter": "false",
            "redact": "false",
            "utterances": "false",
            "filler_words": "false",      # Remove "um", "uh", etc.
            "numerals": "true",           # Convert numbers to digits
        }
        
        if detect_language:
            params["detect_language"] = "true"
        else:
            params["language"] = language
        
        # Add keywords boost for sales vocabulary
        if self.vocabulary_boost:
            params["keywords"] = ":".join(self.vocabulary_boost[:15])  # API limit
        
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": mimetype
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    DEEPGRAM_STT_URL,
                    params=params,
                    headers=headers,
                    content=audio_data
                )
                
                if response.status_code != 200:
                    return {
                        "error": f"Deepgram STT failed: {response.status_code}",
                        "text": ""
                    }
                
                result = response.json()
                
                # Extract transcription
                transcript = ""
                confidence = 0.0
                detected_language = language
                words = []
                
                if "results" in result:
                    channels = result["results"].get("channels", [])
                    if channels:
                        alternatives = channels[0].get("alternatives", [])
                        if alternatives:
                            transcript = alternatives[0].get("transcript", "")
                            confidence = alternatives[0].get("confidence", 0.0)
                            words = alternatives[0].get("words", [])
                    
                    # Get detected language if available
                    if detect_language and "detected_language" in result["results"]:
                        detected_language = result["results"]["detected_language"]
                
                # Clean and enhance the transcription
                cleaned_transcript = self._clean_transcription(transcript)
                
                return {
                    "text": cleaned_transcript,
                    "raw_text": transcript,
                    "confidence": confidence,
                    "language": detected_language,
                    "word_count": len(words),
                    "error": None
                }
                
        except httpx.TimeoutException:
            return {"error": "Transcription timed out", "text": ""}
        except Exception as e:
            return {"error": str(e), "text": ""}
    
    async def synthesize_speech(
        self,
        text: str,
        voice: str = "aura-asteria-en",
        encoding: str = "mp3"
    ) -> dict:
        """
        Synthesize text to speech using Deepgram TTS
        
        Args:
            text: Text to synthesize
            voice: Voice model to use
            encoding: Audio encoding format (mp3, wav, etc.)
        
        Returns:
            Audio data and metadata
        """
        if not self.api_key:
            return {"error": "Deepgram API key not configured", "audio": None}
        
        if not text or not text.strip():
            return {"error": "No text provided", "audio": None}
        
        # MP3 doesn't support sample_rate parameter
        params = {
            "model": voice,
            "encoding": encoding
        }
        
        headers = {
            "Authorization": f"Token {self.api_key}",
            "Content-Type": "text/plain"
        }
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    DEEPGRAM_TTS_URL,
                    params=params,
                    headers=headers,
                    content=text  # Send raw text, not JSON
                )
                
                if response.status_code != 200:
                    error_body = response.text
                    return {
                        "error": f"Deepgram TTS failed: {response.status_code} - {error_body}",
                        "audio": None
                    }
                
                audio_data = response.content
                audio_base64 = base64.b64encode(audio_data).decode("utf-8")
                
                return {
                    "audio": audio_base64,
                    "mimetype": f"audio/{encoding}",
                    "encoding": encoding,
                    "error": None
                }
                
        except httpx.TimeoutException:
            return {"error": "Speech synthesis timed out", "audio": None}
        except Exception as e:
            return {"error": str(e), "audio": None}
    
    def get_available_voices(self) -> list:
        """Get list of available TTS voices"""
        return [
            {"id": "aura-asteria-en", "name": "Asteria", "language": "English", "gender": "Female"},
            {"id": "aura-luna-en", "name": "Luna", "language": "English", "gender": "Female"},
            {"id": "aura-stella-en", "name": "Stella", "language": "English", "gender": "Female"},
            {"id": "aura-athena-en", "name": "Athena", "language": "English", "gender": "Female"},
            {"id": "aura-hera-en", "name": "Hera", "language": "English", "gender": "Female"},
            {"id": "aura-orion-en", "name": "Orion", "language": "English", "gender": "Male"},
            {"id": "aura-arcas-en", "name": "Arcas", "language": "English", "gender": "Male"},
            {"id": "aura-perseus-en", "name": "Perseus", "language": "English", "gender": "Male"},
            {"id": "aura-angus-en", "name": "Angus", "language": "English", "gender": "Male"},
            {"id": "aura-orpheus-en", "name": "Orpheus", "language": "English", "gender": "Male"},
        ]


# Singleton instance
deepgram_service = DeepgramService()


async def transcribe_audio(audio_data: bytes, **kwargs) -> dict:
    """Convenience function for transcription"""
    return await deepgram_service.transcribe_audio(audio_data, **kwargs)


async def synthesize_speech(text: str, **kwargs) -> dict:
    """Convenience function for speech synthesis"""
    return await deepgram_service.synthesize_speech(text, **kwargs)


def get_voices() -> list:
    """Get available voices"""
    return deepgram_service.get_available_voices()
