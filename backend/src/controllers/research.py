from src.services import studies,runs,series
# Controllers keep endpoint contracts separate from persistence and calculation.
def overview(db): return {'studies':studies.list_studies(db),'runs':runs.list_runs(db)}
def create_study(db,data,user): return studies.create(db,data,user)
def list_rows(db,id): return studies.observations(db,id)
def save_row(db,id,data,user,row_id=None): return studies.save_observation(db,id,data,user,row_id)
def create_run(db,data,user): return runs.create(db,data,user)
def review_run(db,id,data,user): return runs.approve(db,id,data,user)
def list_series(db): return series.list_series(db)
def create_series(db,data,user): return series.create_series(db,data,user)
def update_series(db,id,data,user): return series.update_series(db,id,data,user)
def start_series_study(db,id,data,user): return series.start_study(db,id,data,user)
def cancel_series_study(db,id,user): return series.cancel_study(db,id,user)
def retry_series_study(db,id,user): return series.retry_study(db,id,user)
