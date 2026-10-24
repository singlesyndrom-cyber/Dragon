"""Связь приложения Android с сайтом (Digital Asset Links): без неё приложение покажет адресную строку браузера."""
from fastapi import APIRouter

from ..config import settings

router = APIRouter(tags=["app"])


@router.get("/app/assetlinks")
def assetlinks():
    prints = [x.strip().upper() for x in settings.android_cert_sha256.split(",") if x.strip()]
    if not prints:
        return []
    return [{"relation": ["delegate_permission/common.handle_all_urls"],
             "target": {"namespace": "android_app", "package_name": settings.android_package,
                        "sha256_cert_fingerprints": prints}}]
