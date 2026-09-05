from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories import farmers as farmer_repository
from app.schemas.procurement import FarmerCreate, FarmerResponse

router = APIRouter()


@router.post("/", response_model=FarmerResponse, status_code=status.HTTP_201_CREATED)
async def create_farmer(
    farmer_data: FarmerCreate,
    session: Session = Depends(get_db),
) -> FarmerResponse:
    return farmer_repository.create_farmer(session, farmer_data)
