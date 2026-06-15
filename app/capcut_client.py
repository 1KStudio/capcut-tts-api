"""CapCut TTS client - wraps the CapCut API for text-to-speech."""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
import uuid
import base64
from copy import deepcopy
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

import httpx

from app.config import get_settings


# CapCut TTS RSA public key for payload signing
TTS_SIGN_PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmTd34Lw4b7IuldSXh/zY
CMla+ITdGG5TeWz6ad+OySd4r+IrY45AoqrYUxhQ2dl+7z+i7r/5vEa8rr39BYfB
8AGMQLmZA8HmgpWBsqrn/V6daUALkKnkLb70Fn32CJigIuGXAYqxUdGuI340aC+0
v5Es3puJsHyzf01/AelE4Cdc6bZhQrASJLBh8R3BQToYClmDVSDUQk28o8sl/guA
Z4n303Vj+6Siv1HayPCdV6kpVVnMBAG4+umUbwGmn132N3fgpzLarFF3XyWmS1zh
D/J07iM/rP8GDO9IskHNHd2phrO0G6KzrcFAnTBHjVv+hCBEfzN/no3FNA9AuC36
mwIDAQAB
-----END PUBLIC KEY-----"""


def _der_len(data: bytes, pos: int) -> tuple[int, int]:
    first = data[pos]
    pos += 1
    if first < 0x80:
        return first, pos
    nbytes = first & 0x7F
    return int.from_bytes(data[pos : pos + nbytes], "big"), pos + nbytes


def _der_value(data: bytes, pos: int, tag: int) -> tuple[bytes, int]:
    if data[pos] != tag:
        raise ValueError(f"bad DER tag: expected 0x{tag:02x}, got 0x{data[pos]:02x}")
    length, pos = _der_len(data, pos + 1)
    return data[pos : pos + length], pos + length


def _der_int(data: bytes, pos: int) -> tuple[int, int]:
    raw, pos = _der_value(data, pos, 0x02)
    return int.from_bytes(raw.lstrip(b"\x00"), "big"), pos


def rsa_public_numbers_from_pem(pem: str) -> tuple[int, int]:
    b64 = "".join(line for line in pem.splitlines() if not line.startswith("-----"))
    der = base64.b64decode(b64)
    outer, pos = _der_value(der, 0, 0x30)
    if pos != len(der):
        raise ValueError("trailing data in public key")
    _, pos = _der_value(outer, 0, 0x30)
    bit_string, pos = _der_value(outer, pos, 0x03)
    if pos != len(outer) or not bit_string or bit_string[0] != 0:
        raise ValueError("bad subjectPublicKeyInfo")
    rsa_seq, pos = _der_value(bit_string[1:], 0, 0x30)
    if pos != len(bit_string[1:]):
        raise ValueError("trailing data in RSA public key")
    modulus, pos = _der_int(rsa_seq, 0)
    exponent, pos = _der_int(rsa_seq, pos)
    if pos != len(rsa_seq):
        raise ValueError("trailing integer data in RSA public key")
    return modulus, exponent


def rsa_encrypt_pkcs1v15(message: str | bytes, pem: str = TTS_SIGN_PUBLIC_KEY_PEM) -> str:
    modulus, exponent = rsa_public_numbers_from_pem(pem)
    key_len = (modulus.bit_length() + 7) // 8
    msg = message.encode("utf-8") if isinstance(message, str) else bytes(message)
    if len(msg) > key_len - 11:
        raise ValueError("message too long for RSA PKCS#1 v1.5")
    ps_len = key_len - len(msg) - 3
    ps = bytearray()
    while len(ps) < ps_len:
        chunk = secrets.token_bytes(ps_len - len(ps))
        ps.extend(b for b in chunk if b != 0)
    encoded = b"\x00\x02" + bytes(ps[:ps_len]) + b"\x00" + msg
    encrypted = pow(int.from_bytes(encoded, "big"), exponent, modulus).to_bytes(key_len, "big")
    return base64.b64encode(encrypted).decode("ascii")


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def compact_json(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def make_x_ss_stub(body_text: str) -> str:
    return hashlib.md5(body_text.encode("utf-8")).hexdigest()


def make_sign_header(url: str, appvr: str, device_time: str, tdid: str) -> str:
    path = url.split("?", 1)[0]
    sign_str = f"9e2c|{path[-7:]}|3|{appvr}|{device_time}|{tdid}|11ac"
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()


def make_tts_payload_sign(ssml: str, extra_info: str, device_id: str, app_id: str) -> str:
    ssml_md5 = hashlib.md5(ssml.encode("utf-8")).hexdigest()
    sign_input = f"appid:{app_id}&did:{device_id}&creditDisable:false&ssml:{ssml_md5}"
    if extra_info is not None:
        sign_input += f"&extraInfo:{extra_info}"
    return rsa_encrypt_pkcs1v15(sign_input)


def make_trace_id() -> str:
    seed = uuid.uuid4().hex[:32]
    return f"00-{seed}-{seed[:16]}-01"


class CapCutTTSClient:
    """Async client for CapCut TTS API."""

    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.capcut_api_base
        self.device = self._build_device()
        self._client: Optional[httpx.AsyncClient] = None

    def _build_device(self) -> dict:
        """Build device profile from settings or generate random."""
        device_id = self.settings.capcut_device_id
        iid = self.settings.capcut_iid
        tdid = self.settings.capcut_tdid

        if not device_id:
            device_id = str(secrets.randbelow(10**19 - 7 * 10**18) + 7 * 10**18)
        if not iid:
            iid = str(secrets.randbelow(10**19 - 7 * 10**18) + 7 * 10**18)
        if not tdid:
            tdid = device_id

        return {
            "aid": "359289",
            "app_name": "CapCut",
            "appvr": "8.7.0",
            "version_name": "8.7.0",
            "version_code": "8.7.0",
            "channel": "capcutpc_google",
            "device_platform": "mac",
            "device_type": "MacBookPro17,1",
            "device_brand": "MacBookPro17,1",
            "os_version": "15.7.4",
            "device_id": device_id,
            "iid": iid,
            "region": "VN",
            "loc": "VN",
            "lan": "vi-VN",
            "pf": "3",
            "tdid": tdid,
        }

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _common_query(self, babi_param: Optional[dict] = None, include_region: bool = True) -> dict:
        q = {
            "app_name": self.device["app_name"],
            "device_type": self.device["device_type"],
            "os_version": self.device["os_version"],
            "channel": self.device["channel"],
            "version_name": self.device["version_name"],
            "device_brand": self.device["device_brand"],
            "device_id": self.device["device_id"],
            "iid": self.device["iid"],
            "version_code": self.device["version_code"],
            "device_platform": self.device["device_platform"],
            "aid": self.device["aid"],
        }
        if include_region:
            q["region"] = self.device["region"]
        if babi_param is not None:
            q["babi_param"] = compact_json(babi_param)
        return q

    def _base_headers(self, body_text: str, appid: bool = False) -> dict:
        now = str(int(time.time()))
        headers = {
            "content-type": "application/json",
            "appvr": self.device["appvr"],
            "ch": self.device["channel"],
            "device-time": now,
            "lan": self.device["lan"],
            "loc": self.device["loc"],
            "pf": self.device["pf"],
            "sign-ver": "1",
            "tdid": self.device["tdid"],
            "x-ss-stub": make_x_ss_stub(body_text),
            "x-ss-dp": self.device["aid"],
            "x-khronos": now,
            "x-tt-trace-id": make_trace_id(),
            "user-agent": "Cronet/TTNetVersion:1d7cc3b1 2025-07-16 QuicVersion:52c2b40d 2025-04-03",
            "accept-encoding": "gzip, deflate",
            "store-country-code": self.device["loc"].lower(),
            "store-country-code-src": "did",
            "is-dispatch-us-ttp": "0",
            "is-app-region-us-ttp": "0",
        }
        if appid:
            headers["app-sdk-version"] = self.device["appvr"]
            headers["appid"] = self.device["aid"]
        return headers

    def _build_tts_body(
        self, text: str, voice: str, resource_id: str, rate: float = 1.0
    ) -> tuple[dict, dict]:
        babi = {
            "feature_entrance": "editor",
            "feature_entrance_detail": "editor-feature-text_to_speech",
            "feature_key": "text_to_speech",
            "scenario": "video_editor",
        }
        ssml = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">\n'
            f'    <voice name="{voice}" mock_tone_info="" platform="sami" '
            f'resource_id="{resource_id}" emotion="" emotion_scale="0" style="" role="" '
            f'moyin_emotion="" is_clone_tone="false" need_subtitle_timestamp="false">\n'
            f'        <prosody rate="{rate}">{escape_xml(text)}</prosody>\n'
            f"    </voice>\n"
            "</speak>"
        )
        extra_info = compact_json({"benefit_info": {}})
        payload = {
            "audio_format": "mp3",
            "babi_param": compact_json(babi),
            "credit_disable": False,
            "extra_info": extra_info,
            "need_merge_voice": False,
            "need_subtitle_timestamp": False,
            "scene": "text_to_speech",
            "ssml": ssml,
        }
        payload["sign"] = make_tts_payload_sign(
            ssml, extra_info, self.device["device_id"], self.device["aid"]
        )
        body = {
            "bind_id": str(uuid.uuid4()),
            "can_queue": True,
            "enter_from": "text_to_speech",
            "tasks": [
                {
                    "context": str(uuid.uuid4()),
                    "payload": compact_json(payload),
                    "req_key": "sami_text_to_speech",
                    "task_version": "v3",
                }
            ],
        }
        return babi, body

    async def submit_tts(
        self, text: str, voice: str, resource_id: str, rate: float = 1.0
    ) -> tuple[str, str]:
        """Submit TTS task and return (task_id, token)."""
        babi, body = self._build_tts_body(text, voice, resource_id, rate)
        path = "/lv/v1/common_task/new"
        query = self._common_query(babi, include_region=True)
        url = self.base_url + path + "?" + urlencode(query)
        body_text = compact_json(body)
        headers = self._base_headers(body_text, appid=True)
        headers["sign"] = make_sign_header(
            url, self.device["appvr"], headers["device-time"], self.device["tdid"]
        )

        client = await self._get_client()
        resp = await client.post(url, headers=headers, content=body_text.encode("utf-8"))
        data = resp.json()

        if data.get("ret") != "0":
            raise RuntimeError(f"CapCut API error: {data.get('errmsg', 'unknown')}")

        tasks = data.get("data", {}).get("tasks", [])
        if not tasks:
            raise RuntimeError("No task returned from CapCut API")

        task = tasks[0]
        return task["id"], task["token"]

    async def poll_tts(self, task_id: str, token: str) -> dict:
        """Poll TTS task until completion. Returns payload dict."""
        path = "/lv/v1/common_task/query"
        query = self._common_query(include_region=False)
        url = self.base_url + path + "?" + urlencode(query)

        body = {
            "tasks": [
                {
                    "bind_id": "",
                    "id": task_id,
                    "req_key": "sami_text_to_speech",
                    "task_version": "v3",
                    "token": token,
                }
            ]
        }

        client = await self._get_client()

        for _ in range(self.settings.poll_max_attempts):
            body_text = compact_json(body)
            headers = self._base_headers(body_text, appid=True)
            headers["sign"] = make_sign_header(
                url, self.device["appvr"], headers["device-time"], self.device["tdid"]
            )

            resp = await client.post(url, headers=headers, content=body_text.encode("utf-8"))
            data = resp.json()

            if data.get("ret") != "0":
                raise RuntimeError(f"CapCut poll error: {data.get('errmsg', 'unknown')}")

            tasks = data.get("data", {}).get("tasks", [])
            if tasks:
                task = tasks[0]
                status = task.get("status")
                if status == "succeed":
                    return json.loads(task["payload"])
                elif status == "failed":
                    raise RuntimeError(f"TTS task failed: {task.get('detail_info', '')}")

            await asyncio.sleep(self.settings.poll_interval)

        raise TimeoutError(f"TTS task did not complete within {self.settings.poll_max_attempts} attempts")

    async def synthesize(
        self, text: str, voice: str, resource_id: str, rate: float = 1.0
    ) -> tuple[bytes, dict]:
        """Full TTS flow: submit, poll, download. Returns (audio_bytes, metadata)."""
        task_id, token = await self.submit_tts(text, voice, resource_id, rate)
        payload = await self.poll_tts(task_id, token)

        audio_subtitles = payload.get("audio_subtitles", [])
        if not audio_subtitles:
            raise RuntimeError("No audio returned from CapCut")

        audio_info = audio_subtitles[0]
        speech_url = audio_info.get("speech_url")
        if not speech_url:
            raise RuntimeError("No speech_url in response")

        client = await self._get_client()
        resp = await client.get(speech_url, follow_redirects=True)
        audio_bytes = resp.content

        metadata = {
            "duration_ms": audio_info.get("duration", 0),
            "speaker_id": audio_info.get("speaker_id", voice),
            "text": audio_info.get("text", text),
        }
        return audio_bytes, metadata

    def get_voice_for_language(self, language: str) -> tuple[str, str]:
        """Get default voice and resource_id for a language code."""
        lang = language.lower()
        if lang.startswith("de"):
            return self.settings.default_voice_de, self.settings.default_resource_id_de
        elif lang.startswith("vi"):
            return self.settings.default_voice_vi, self.settings.default_resource_id_vi
        else:
            # Default to Vietnamese
            return self.settings.default_voice_vi, self.settings.default_resource_id_vi


# Singleton
_tts_client: Optional[CapCutTTSClient] = None


def get_tts_client() -> CapCutTTSClient:
    global _tts_client
    if _tts_client is None:
        _tts_client = CapCutTTSClient()
    return _tts_client
