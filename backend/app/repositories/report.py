from app.db.session import SessionLocal
from app.db.models.report import Report

class ReportRepository:
    def __init__(self):
        self.db = SessionLocal()

    def create(self, content: str):
        r = Report(content=content)
        self.db.add(r)
        self.db.commit()
        self.db.refresh(r)
        return r

    def get(self, report_id: int):
        return self.db.query(Report).filter(Report.id == report_id).first()
