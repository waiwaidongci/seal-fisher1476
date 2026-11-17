from sqlalchemy import Column,Integer,String,JSON,Text,ForeignKey,Boolean,Numeric
from src.config.database import Base
class ResearchSeries(Base):
    __tablename__='series'
    id=Column(Integer,primary_key=True)
    name=Column(String(120),unique=True,nullable=False)
    total_budget=Column(Numeric(12,9),nullable=False)
    locked=Column(Boolean,default=False,nullable=False)
    created_at=Column(String(40),nullable=False)
Series=ResearchSeries
class SeriesStudy(Base):
    __tablename__='series_studies'
    id=Column(Integer,primary_key=True)
    series_id=Column(Integer,ForeignKey('series.id'),nullable=False)
    study_id=Column(Integer,ForeignKey('studies.id'),nullable=False)
    name=Column(String(120),nullable=False)
    status=Column(String(20),default='queued')
    alpha=Column(Numeric(12,9),nullable=False)
    budget_state=Column(String(20),default='reserved')
    parameters=Column(JSON,nullable=False)
    snapshot=Column(JSON,nullable=False)
    checksum=Column(String(64),nullable=False)
    result=Column(JSON,nullable=True)
    error=Column(Text,default='')
    created_at=Column(String(40),nullable=False)
class SeriesLedger(Base):
    __tablename__='series_ledger'
    id=Column(Integer,primary_key=True)
    series_id=Column(Integer,ForeignKey('series.id'),nullable=False)
    study_ref=Column(Integer,nullable=True)
    action=Column(String(20),nullable=False)
    amount=Column(Numeric(12,9),nullable=False)
    used=Column(Numeric(12,9),nullable=False)
    reserved=Column(Numeric(12,9),nullable=False)
    reason=Column(String(300),nullable=False)
    created_at=Column(String(40),nullable=False)
