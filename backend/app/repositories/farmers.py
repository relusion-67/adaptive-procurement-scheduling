from sqlalchemy.orm import Session

from app.models import Farmer
from app.schemas.procurement import FarmerCreate


def create_farmer(session: Session, farmer_data: FarmerCreate) -> Farmer:
    farmer = Farmer(**farmer_data.model_dump())
    session.add(farmer)
    session.commit()
    session.refresh(farmer)
    return farmer



def get_farmer(session: Session, farmer_id: int) -> Farmer | None:
    return session.get(Farmer, farmer_id)
