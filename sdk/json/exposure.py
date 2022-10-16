
class Exposure:
    def __init__(self):
        self.id: int
        self.name: str
        self.unit: str
        self.variant: int
        self.exposed_at: int
        self.assigned: bool
        self.eligible: bool
        self.overridden: bool
        self.full_on: bool
        self.custom: bool
        self.audience_mismatch: bool
