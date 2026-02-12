"""
AI Assistant API Routes
Chatbot and Voice Assistant endpoints
"""
from fastapi import APIRouter, Request, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import Optional, List
import json
import uuid
import base64

from app.services.ai_assistant import (
    stream_chat_response,
    get_chat_response,
    clear_conversation,
    get_conversation_summary,
    detect_intent,
    get_or_create_context
)
from app.services.voice_service import (
    transcribe_audio,
    synthesize_speech,
    get_voices
)

router = APIRouter()


# Request/Response Models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    stream: bool = True


class ChatResponse(BaseModel):
    response: str
    session_id: str
    intent: Optional[dict] = None


class VoiceTranscribeRequest(BaseModel):
    audio_base64: str
    mimetype: str = "audio/webm"
    language: str = "en"
    detect_language: bool = False


class VoiceSynthesizeRequest(BaseModel):
    text: str
    voice: str = "aura-asteria-en"


class ClearConversationRequest(BaseModel):
    session_id: str


# Chat Endpoints
@router.post("/chat")
async def chat(request: ChatRequest):
    """
    Send a message to the AI chatbot (non-streaming)
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Get intent for analytics
    intent = detect_intent(request.message)
    
    if request.stream:
        # Return streaming response
        async def generate():
            async for chunk in stream_chat_response(session_id, request.message):
                yield {
                    "event": "message",
                    "data": json.dumps({"content": chunk, "session_id": session_id})
                }
            yield {
                "event": "done",
                "data": json.dumps({"session_id": session_id, "intent": intent})
            }
        
        return EventSourceResponse(generate())
    else:
        # Non-streaming response
        response = await get_chat_response(session_id, request.message)
        return ChatResponse(
            response=response,
            session_id=session_id,
            intent=intent
        )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    Send a message to the AI chatbot with SSE streaming response
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    intent = detect_intent(request.message)
    
    async def generate():
        yield {
            "event": "start",
            "data": json.dumps({"session_id": session_id})
        }
        
        async for chunk in stream_chat_response(session_id, request.message):
            yield {
                "event": "chunk",
                "data": json.dumps({"content": chunk})
            }
        
        yield {
            "event": "done",
            "data": json.dumps({"session_id": session_id, "intent": intent})
        }
    
    return EventSourceResponse(generate())


@router.post("/chat/clear")
async def clear_chat(request: ClearConversationRequest):
    """
    Clear conversation history for a session
    """
    clear_conversation(request.session_id)
    return {"status": "cleared", "session_id": request.session_id}


@router.get("/chat/summary/{session_id}")
async def get_chat_summary(session_id: str):
    """
    Get conversation summary for a session
    """
    summary = get_conversation_summary(session_id)
    return summary


# Voice Endpoints
@router.post("/voice/transcribe")
async def voice_transcribe(request: VoiceTranscribeRequest):
    """
    Transcribe audio to text using Deepgram STT
    """
    try:
        audio_data = base64.b64decode(request.audio_base64)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid base64 audio data")
    
    result = await transcribe_audio(
        audio_data,
        mimetype=request.mimetype,
        language=request.language,
        detect_language=request.detect_language
    )
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result


@router.post("/voice/transcribe-file")
async def voice_transcribe_file(
    audio: UploadFile = File(...),
    language: str = Form("en"),
    detect_language: bool = Form(False)
):
    """
    Transcribe uploaded audio file to text
    """
    audio_data = await audio.read()
    mimetype = audio.content_type or "audio/webm"
    
    result = await transcribe_audio(
        audio_data,
        mimetype=mimetype,
        language=language,
        detect_language=detect_language
    )
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result


@router.post("/voice/synthesize")
async def voice_synthesize(request: VoiceSynthesizeRequest):
    """
    Synthesize text to speech using Deepgram TTS
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")
    
    result = await synthesize_speech(
        request.text,
        voice=request.voice
    )
    
    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])
    
    return result


@router.get("/voice/voices")
async def get_available_voices():
    """
    Get list of available TTS voices
    """
    return {"voices": get_voices()}


# Voice Chat - Combined STT + Chat + TTS
@router.post("/voice/chat")
async def voice_chat(
    audio: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    voice: str = Form("aura-asteria-en"),
    language: str = Form("en")
):
    """
    Complete voice chat: transcribe audio, get AI response, synthesize speech
    """
    session_id = session_id or str(uuid.uuid4())
    
    # 1. Transcribe audio
    audio_data = await audio.read()
    mimetype = audio.content_type or "audio/webm"
    
    transcription = await transcribe_audio(
        audio_data,
        mimetype=mimetype,
        language=language
    )
    
    if transcription.get("error"):
        raise HTTPException(status_code=500, detail=f"Transcription failed: {transcription['error']}")
    
    user_text = transcription.get("text", "")
    if not user_text.strip():
        return {
            "session_id": session_id,
            "user_text": "",
            "assistant_text": "I didn't catch that. Could you please speak again?",
            "audio": None,
            "error": "No speech detected"
        }
    
    # 2. Get AI response
    assistant_text = await get_chat_response(session_id, user_text)
    
    # 3. Synthesize response
    synthesis = await synthesize_speech(assistant_text, voice=voice)
    
    return {
        "session_id": session_id,
        "user_text": user_text,
        "assistant_text": assistant_text,
        "audio": synthesis.get("audio"),
        "mimetype": synthesis.get("mimetype"),
        "confidence": transcription.get("confidence"),
        "intent": detect_intent(user_text)
    }
