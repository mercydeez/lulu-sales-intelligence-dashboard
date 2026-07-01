"""
AI Assistant API Routes
Chatbot and Voice Assistant endpoints
"""
from fastapi import APIRouter, Request, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
import uuid
import base64

from app.config import get_settings

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
from app.routes.auth import get_current_user, get_accessible_store_ids

router = APIRouter()


# =============================================================================
# AI ACCESS GATES (server-side — must mirror the UI gate in ChatBot.tsx so a
# direct API call cannot bypass it). can_use_ai_chat / can_use_voice_chat are
# optional per-user grants on top of the always-allowed manager roles.
# =============================================================================
_AI_CHAT_ROLES = ("super_admin", "regional_manager", "store_manager")
_AI_VOICE_ROLES = ("super_admin", "regional_manager")


def require_ai_chat(user: dict = Depends(get_current_user)) -> dict:
    """Allow the manager roles, or any user explicitly granted can_use_ai_chat."""
    perms = user.get("permissions", {}) or {}
    if user.get("role") in _AI_CHAT_ROLES or perms.get("can_use_ai_chat"):
        return user
    raise HTTPException(status_code=403, detail="You do not have access to the AI assistant.")


def require_voice_chat(user: dict = Depends(get_current_user)) -> dict:
    """Voice is more restricted: manager roles or an explicit can_use_voice_chat grant."""
    perms = user.get("permissions", {}) or {}
    if user.get("role") in _AI_VOICE_ROLES or perms.get("can_use_voice_chat"):
        return user
    raise HTTPException(status_code=403, detail="You do not have access to voice chat.")


def _scoped_session(user: dict, session_id: str) -> str:
    """Namespace the client-supplied session id with the authenticated user id so
    one user can never read, continue, or clear another user's conversation
    context by guessing/reusing a session_id (P0.3). The raw session_id is still
    returned to the client; the route always re-scopes it with the same user id."""
    return f"u{user.get('id')}:{session_id}"


async def _meter_sage_message(tenant_id: int, intent) -> None:
    """Soft-enforce the billing-period Sage quota then meter the message (Phase 3).
    Raises 429 ONLY when ENFORCE_USAGE_QUOTAS is on and the plan is over limit;
    otherwise best-effort — never breaks the chat on a metering error."""
    from app.services.usage_metering import record_usage, check_quota
    from app.services.database import async_session
    try:
        async with async_session() as _s:
            allowed, _ = await check_quota(_s, tenant_id, "sage_message")
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Monthly Sage message limit reached for your plan. Upgrade to continue.")
    except HTTPException:
        raise
    except Exception:
        pass
    await record_usage(tenant_id, "sage_message",
                       metadata={"intent": str(intent) if intent is not None else None})


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
async def chat(request: ChatRequest, current_user: dict = Depends(require_ai_chat)):
    """
    Send a message to the AI chatbot (non-streaming)
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    # Get intent for analytics
    intent = detect_intent(request.message)

    # RBAC: restrict every data query to the stores this user may see.
    # Empty list => super_admin (all stores in the tenant); see get_accessible_store_ids.
    allowed_stores = get_accessible_store_ids(current_user)
    tenant_id = current_user.get('tenant_id') or 1
    role = current_user.get('role') or 'store_manager'
    scoped_session = _scoped_session(current_user, session_id)

    # Usage metering (Phase 3): soft-enforce the billing-period Sage quota, then
    # meter this message. Best-effort — a metering failure never blocks the chat;
    # a hard 429 only fires when ENFORCE_USAGE_QUOTAS is on AND the plan is over.
    await _meter_sage_message(tenant_id, intent)

    # Sage v3 (multi-agent graph) — gated; falls back to the v2 path when off.
    if get_settings().use_sage_v3:
        from app.services.sage3.runtime import answer_sage3, sage3_meta
        if request.stream:
            async def generate_v3():
                state = await answer_sage3(scoped_session, request.message, tenant_id, role, allowed_stores)
                answer = state.get("final_answer", "") or ""
                words = answer.split(" ")
                for i, word in enumerate(words):
                    yield {
                        "event": "message",
                        "data": json.dumps({"content": word + (" " if i < len(words) - 1 else ""),
                                            "session_id": session_id})
                    }
                    await asyncio.sleep(0.01)
                yield {
                    "event": "done",
                    "data": json.dumps({"session_id": session_id, "intent": intent, **sage3_meta(state)})
                }
            return EventSourceResponse(generate_v3())
        state = await answer_sage3(scoped_session, request.message, tenant_id, role, allowed_stores)
        return ChatResponse(response=state.get("final_answer", ""), session_id=session_id,
                            intent={**(intent or {}), **sage3_meta(state)})

    if request.stream:
        # Return streaming response
        async def generate():
            async for chunk in stream_chat_response(scoped_session, request.message, tenant_id, role, allowed_stores):
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
        response = await get_chat_response(scoped_session, request.message, tenant_id, role, allowed_stores)
        return ChatResponse(
            response=response,
            session_id=session_id,
            intent=intent
        )


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, current_user: dict = Depends(require_ai_chat)):
    """
    Send a message to the AI chatbot with SSE streaming response
    """
    session_id = request.session_id or str(uuid.uuid4())
    
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    
    intent = detect_intent(request.message)

    allowed_stores = get_accessible_store_ids(current_user)
    tenant_id = current_user.get('tenant_id') or 1
    role = current_user.get('role') or 'store_manager'
    scoped_session = _scoped_session(current_user, session_id)

    # Usage metering (Phase 3) — soft-enforce + meter before the stream opens.
    await _meter_sage_message(tenant_id, intent)

    use_v3 = get_settings().use_sage_v3

    async def generate():
        yield {
            "event": "start",
            "data": json.dumps({"session_id": session_id})
        }

        if use_v3:
            from app.services.sage3.runtime import answer_sage3, sage3_meta
            state = await answer_sage3(scoped_session, request.message, tenant_id, role, allowed_stores)
            answer = state.get("final_answer", "") or ""
            words = answer.split(" ")
            for i, word in enumerate(words):
                yield {"event": "chunk",
                       "data": json.dumps({"content": word + (" " if i < len(words) - 1 else "")})}
                await asyncio.sleep(0.01)
            yield {
                "event": "done",
                "data": json.dumps({"session_id": session_id, "intent": intent, **sage3_meta(state)})
            }
            return

        async for chunk in stream_chat_response(scoped_session, request.message, tenant_id, role, allowed_stores):
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
async def clear_chat(request: ClearConversationRequest, current_user: dict = Depends(require_ai_chat)):
    """
    Clear conversation history for a session
    """
    clear_conversation(_scoped_session(current_user, request.session_id))
    return {"status": "cleared", "session_id": request.session_id}


@router.get("/chat/summary/{session_id}")
async def get_chat_summary(session_id: str, current_user: dict = Depends(require_ai_chat)):
    """
    Get conversation summary for a session
    """
    summary = get_conversation_summary(_scoped_session(current_user, session_id))
    return summary


# Voice Endpoints
@router.post("/voice/transcribe")
async def voice_transcribe(request: VoiceTranscribeRequest, current_user: dict = Depends(require_voice_chat)):
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
    detect_language: bool = Form(False),
    current_user: dict = Depends(require_voice_chat)
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
async def voice_synthesize(request: VoiceSynthesizeRequest, current_user: dict = Depends(require_voice_chat)):
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
async def get_available_voices(current_user: dict = Depends(require_voice_chat)):
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
    language: str = Form("en"),
    current_user: dict = Depends(require_voice_chat)
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
    
    # 2. Get AI response (RBAC: scoped to the caller's stores + session bound to user)
    _vt = current_user.get('tenant_id') or 1
    _vr = current_user.get('role') or 'store_manager'
    _vs = get_accessible_store_ids(current_user)
    if get_settings().use_sage_v3:
        from app.services.sage3.runtime import get_sage3_chat
        assistant_text = await get_sage3_chat(
            _scoped_session(current_user, session_id), user_text, _vt, _vr, _vs)
    else:
        assistant_text = await get_chat_response(
            _scoped_session(current_user, session_id), user_text, _vt, _vr, _vs)
    
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
