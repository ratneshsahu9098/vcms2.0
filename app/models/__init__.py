from app.extensions import db
from app.models.chat import ChatMessage, ChatSession
from app.models.document_scan import DocumentScan
from app.models.reminder_log import ReminderLog
from app.models.tax import TaxDetail
from app.models.vehicle import Vehicle, DocumentExpiry

__all__ = ["db", "Vehicle", "DocumentExpiry", "TaxDetail", "ReminderLog", "DocumentScan", "ChatSession", "ChatMessage"]
