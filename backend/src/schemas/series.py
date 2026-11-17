from pydantic import BaseModel,Field
class SeriesInput(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    total_budget:float=Field(gt=0)
class SeriesBudgetInput(BaseModel):
    total_budget:float=Field(gt=0)
class SeriesStudyInput(BaseModel):
    study_id:int=Field(gt=0)
    name:str=Field(min_length=2,max_length=120)
    alpha:float|None=Field(default=None,gt=0)
