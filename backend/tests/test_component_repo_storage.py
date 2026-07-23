"""Tests for metadata-only Component Repo storage operations."""

from unittest.mock import patch

import httpx

from src.component_repo.storage import SupabaseArtifactStorage


def test_supabase_head_uses_object_info_without_downloading_body() -> None:
    storage = SupabaseArtifactStorage(
        supabase_url="https://project.supabase.co",
        api_key="service-key",
        bucket="component-artifacts",
    )
    request = httpx.Request("GET", "https://project.supabase.co/storage/v1/object/info/test")
    response = httpx.Response(
        200,
        request=request,
        json={
            "size": 1234,
            "content_type": "model/gltf-binary",
            "etag": "model-etag",
        },
    )

    with patch("src.component_repo.storage.httpx.get", return_value=response) as get:
        metadata = storage.head("previews/model.glb")

    assert get.call_args.args[0].endswith(
        "/storage/v1/object/info/component-artifacts/previews/model.glb"
    )
    assert metadata.content_length == 1234
    assert metadata.content_type == "model/gltf-binary"
    assert metadata.etag == "model-etag"


def test_supabase_signed_download_url_is_absolute() -> None:
    storage = SupabaseArtifactStorage(
        supabase_url="https://project.supabase.co",
        api_key="service-key",
        bucket="component-artifacts",
    )
    request = httpx.Request("POST", "https://project.supabase.co/storage/v1/object/sign/test")
    response = httpx.Response(
        200,
        request=request,
        json={"signedURL": "/storage/v1/object/sign/component-artifacts/model.glb?token=x"},
    )

    with patch("src.component_repo.storage.httpx.post", return_value=response) as post:
        url = storage.create_download_url("model.glb", 900)

    assert post.call_args.kwargs["json"] == {"expiresIn": 900}
    assert url == (
        "https://project.supabase.co/storage/v1/object/sign/"
        "component-artifacts/model.glb?token=x"
    )
