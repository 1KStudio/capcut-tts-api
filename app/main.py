"""CapCut TTS API Service - FastAPI application."""

import hashlib
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.capcut_client import CapCutTTSClient, get_tts_client
from app.config import get_settings
from app.s3_client import S3Client, get_s3_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifecycle."""
    # Startup
    yield
    # Shutdown
    tts_client = get_tts_client()
    await tts_client.close()


app = FastAPI(
    title="CapCut TTS Service",
    description="Text-to-Speech API using CapCut with S3 upload",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TTSRequest(BaseModel):
    """Request model for TTS synthesis."""

    text: str = Field(..., min_length=1, max_length=5000, description="Text to synthesize")
    language: str = Field(default="vi", description="Language code (vi, de, en, etc.)")
    voice: Optional[str] = Field(default=None, description="Voice ID (overrides language default)")
    resource_id: Optional[str] = Field(default=None, description="Resource ID for voice")
    rate: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech rate (0.5-2.0)")
    s3_prefix: str = Field(default="tts", description="S3 key prefix")


class TTSResponse(BaseModel):
    """Response model for TTS synthesis."""

    url: str = Field(..., description="Public URL of the generated audio")
    duration_ms: int = Field(..., description="Audio duration in milliseconds")
    speaker_id: str = Field(..., description="Voice ID used")
    text: str = Field(..., description="Original text")
    s3_key: str = Field(..., description="S3 object key")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    version: str


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/tts", response_model=TTSResponse, tags=["TTS"])
async def synthesize_speech(request: TTSRequest):
    """
    Synthesize text to speech and upload to S3.

    - **text**: Text to synthesize (max 5000 chars)
    - **language**: Language code (vi, de, en, etc.)
    - **voice**: Optional voice ID override
    - **resource_id**: Optional resource ID for voice
    - **rate**: Speech rate (0.5-2.0)
    - **s3_prefix**: S3 key prefix (default: tts)

    Returns public URL of the generated audio file.
    """
    settings = get_settings()
    tts_client: CapCutTTSClient = get_tts_client()
    s3_client: S3Client = get_s3_client()

    # Get voice and resource_id
    if request.voice and request.resource_id:
        voice = request.voice
        resource_id = request.resource_id
    else:
        voice, resource_id = tts_client.get_voice_for_language(request.language)
        if request.voice:
            voice = request.voice

    # Generate S3 key
    content_hash = hashlib.md5(request.text.encode()).hexdigest()[:8]
    s3_key = f"{request.s3_prefix}/{request.language}/{uuid.uuid4().hex[:8]}_{content_hash}.mp3"

    try:
        # Synthesize speech
        audio_bytes, metadata = await tts_client.synthesize(
            text=request.text,
            voice=voice,
            resource_id=resource_id,
            rate=request.rate,
        )

        # Upload to S3
        url = await s3_client.upload_bytes(s3_key, audio_bytes, content_type="audio/mpeg")

        return TTSResponse(
            url=url,
            duration_ms=metadata.get("duration_ms", 0),
            speaker_id=metadata.get("speaker_id", voice),
            text=metadata.get("text", request.text),
            s3_key=s3_key,
        )

    except TimeoutError as e:
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")


@app.get("/voices", tags=["TTS"])
async def list_voices():
    """List available default voices."""
    settings = get_settings()
    return {
        "vi": {
            "voice": settings.default_voice_vi,
            "resource_id": settings.default_resource_id_vi,
            "name": "Vietnamese default",
        },
        "de": {
            "voice": settings.default_voice_de,
            "resource_id": settings.default_resource_id_de,
            "name": "German default",
        },
    }


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
