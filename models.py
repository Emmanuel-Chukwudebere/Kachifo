from datetime import datetime, date

# This file is being kept as a placeholder for future data structures
# that might be needed without relying on a database.

class TrendData:
    """In-memory representation of trend data"""
    def __init__(self, query, category, title):
        self.query = query
        self.category = category
        self.title = title
        self.timestamp = datetime.utcnow()

class UserQueryData:
    """In-memory representation of user query data"""
    def __init__(self, query):
        self.query = query
        self.timestamp = datetime.utcnow()

class UsageData:
    """In-memory representation of usage statistics"""
    def __init__(self):
        self.date = date.today()
        self.count = 0
        
    def increment(self):
        self.count += 1
