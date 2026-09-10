from enum import Enum


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
