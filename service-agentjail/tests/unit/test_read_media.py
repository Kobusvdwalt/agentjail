import base64

import httpx
import pytest

from agentjail.sandbox.manager import SandboxManager

# Minimal 1×1 red PNG (67 bytes)
_PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Minimal valid WAV header (44 bytes silence)
_WAV_HEADER = (
    b"RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00"
    b"D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00"
)


class TestSandboxReadMedia:
    async def test_read_png(self, manager: SandboxManager, client: httpx.AsyncClient):
        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            resp = await client.post(
                f"/sandbox/{sandbox_id}/fs/upload",
                files={"file": ("photo.png", _PNG_1x1, "image/png")},
            )
            assert resp.status_code == 200

            data, mime = await manager.sandbox_read_media(
                sandbox_id, "/uploads/photo.png"
            )
            assert mime == "image/png"
            assert data == _PNG_1x1
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})

    async def test_read_wav(self, manager: SandboxManager, client: httpx.AsyncClient):
        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            resp = await client.post(
                f"/sandbox/{sandbox_id}/fs/upload",
                files={"file": ("audio.wav", _WAV_HEADER, "audio/wav")},
            )
            assert resp.status_code == 200

            data, mime = await manager.sandbox_read_media(
                sandbox_id, "/uploads/audio.wav"
            )
            assert mime == "audio/x-wav" or mime == "audio/wav"
            assert data == _WAV_HEADER
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})

    async def test_unsupported_type_raises(
        self, manager: SandboxManager, client: httpx.AsyncClient
    ):
        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            await client.post(
                f"/sandbox/{sandbox_id}/fs/upload",
                files={"file": ("data.csv", b"a,b,c", "text/csv")},
            )
            with pytest.raises(ValueError, match="Unsupported media type"):
                await manager.sandbox_read_media(sandbox_id, "/uploads/data.csv")
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})

    async def test_missing_file_raises(
        self, manager: SandboxManager, client: httpx.AsyncClient
    ):
        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            with pytest.raises(FileNotFoundError):
                await manager.sandbox_read_media(sandbox_id, "/uploads/nope.png")
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})

    async def test_unknown_extension_raises(
        self, manager: SandboxManager, client: httpx.AsyncClient
    ):
        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            await client.post(
                f"/sandbox/{sandbox_id}/fs/upload",
                files={"file": ("file.xyz123", b"data", "application/octet-stream")},
            )
            with pytest.raises(ValueError, match="Cannot determine MIME type"):
                await manager.sandbox_read_media(sandbox_id, "/uploads/file.xyz123")
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})


class TestMcpSandboxReadMedia:
    """Test that the MCP tool returns proper ImageContent / AudioContent."""

    async def test_mcp_returns_image_content(
        self, manager: SandboxManager, client: httpx.AsyncClient
    ):
        from agentjail.mcp import server as mcp_server
        from agentjail.mcp.server import sandbox_read_media as mcp_read_media
        from mcp.types import ImageContent

        mcp_server._manager = manager

        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            await client.post(
                f"/sandbox/{sandbox_id}/fs/upload",
                files={"file": ("photo.png", _PNG_1x1, "image/png")},
            )
            result = await mcp_read_media(sandbox_id, "/uploads/photo.png")
            assert isinstance(result, ImageContent)
            assert result.type == "image"
            assert result.mimeType == "image/png"
            assert base64.b64decode(result.data) == _PNG_1x1
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})

    async def test_mcp_returns_audio_content(
        self, manager: SandboxManager, client: httpx.AsyncClient
    ):
        from agentjail.mcp import server as mcp_server
        from agentjail.mcp.server import sandbox_read_media as mcp_read_media
        from mcp.types import AudioContent

        mcp_server._manager = manager

        resp = await client.post("/sandbox", json={})
        sandbox_id = resp.json()["id"]
        try:
            await client.post(
                f"/sandbox/{sandbox_id}/fs/upload",
                files={"file": ("audio.wav", _WAV_HEADER, "audio/wav")},
            )
            result = await mcp_read_media(sandbox_id, "/uploads/audio.wav")
            assert isinstance(result, AudioContent)
            assert result.type == "audio"
            assert base64.b64decode(result.data) == _WAV_HEADER
        finally:
            await client.delete(f"/sandbox/{sandbox_id}", params={"force": True})
