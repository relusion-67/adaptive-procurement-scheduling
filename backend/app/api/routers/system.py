from fastapi import APIRouter

router = APIRouter()


@router.get("/test")
async def api_test() -> dict[str, str]:
    return {"message": "React successfully connected to FastAPI!"}
