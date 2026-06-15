# CapCut TTS Service

FastAPI service that wraps CapCut's TTS API with automatic S3 upload.

## Features

- Text-to-Speech using CapCut API
- Automatic upload to Cloudflare R2 (S3-compatible)
- Support for Vietnamese, German, and other languages
- Async/await throughout
- Docker-ready

## Quick Start

### Local Development

```bash
# Install uv if not installed
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Copy and configure .env
cp .env.example .env
# Edit .env with your R2 credentials

# Run
uv run uvicorn app.main:app --reload
```

### Docker

```bash
# Copy and configure .env
cp .env.example .env
# Edit .env with your R2 credentials

# Build and run
docker compose up -d
```

## API Endpoints

### POST /tts

Synthesize text to speech and upload to S3.

**Request:**
```json
{
  "text": "Xin chào, đây là BlauBerry",
  "language": "vi",
  "voice": null,
  "resource_id": null,
  "rate": 1.0,
  "s3_prefix": "tts"
}
```

**Response:**
```json
{
  "url": "https://storage.colenboro.xyz/tts/vi/abc123_def456.mp3",
  "duration_ms": 2500,
  "speaker_id": "BV074_streaming",
  "text": "Xin chào, đây là BlauBerry",
  "s3_key": "tts/vi/abc123_def456.mp3"
}
```

### GET /voices

List available default voices.

### GET /health

Health check endpoint.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `HOST` | Server host | `0.0.0.0` |
| `PORT` | Server port | `8001` |
| `DEBUG` | Debug mode | `false` |
| `R2_ACCOUNT_ID` | Cloudflare account ID | - |
| `R2_ACCESS_KEY_ID` | R2 access key | - |
| `R2_SECRET_ACCESS_KEY` | R2 secret key | - |
| `R2_BUCKET_NAME` | R2 bucket name | `german-learning` |
| `R2_PUBLIC_URL` | R2 public URL | `https://storage.colenboro.xyz` |
| `CAPCUT_DEVICE_ID` | CapCut device ID (optional) | auto-generated |
| `CAPCUT_IID` | CapCut IID (optional) | auto-generated |
| `DEFAULT_VOICE_VI` | Default Vietnamese voice | `BV074_streaming` |
| `DEFAULT_VOICE_DE` | Default German voice | `DiT_de_male_koubo` |

## Usage Examples

### cURL

```bash
# Vietnamese TTS
curl -X POST http://localhost:8001/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Xin chào, đây là BlauBerry",
    "language": "vi"
  }'

# German TTS
curl -X POST http://localhost:8001/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Willkommen bei BlauBerry",
    "language": "de"
  }'

# Custom voice and rate
curl -X POST http://localhost:8001/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Diese Kultur hat einige Vorteile.",
    "language": "de",
    "voice": "DiT_de_female_qingsong",
    "resource_id": "7584344912292760848",
    "rate": 1.2
  }'
```

### Python

```python
import httpx

response = httpx.post(
    "http://localhost:8001/tts",
    json={
        "text": "Xin chào",
        "language": "vi"
    }
)
data = response.json()
print(data["url"])  # https://storage.colenboro.xyz/tts/vi/...
```

## Available German Voices

| Voice ID | Name | Resource ID |
|----------|------|-------------|
| `DiT_de_male_koubo` | Koubo (male) | `7584344912276114704` |
| `DiT_de_female_jiangshi` | TieFE Dozen (female) | `7584344912292777232` |
| `DiT_de_female_qingsong` | Sanfte Führerin (female) | `7584344912292760848` |

## Notes

- CapCut API may rate-limit or block if abused
- Device IDs are auto-generated if not provided
- Audio is cached on S3 - same text may produce different URLs
- Max text length: 5000 characters

## License

MIT
