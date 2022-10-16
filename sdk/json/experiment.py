from sdk.json.experiement_application import ExperimentApplication
from sdk.json.experiment_variant import ExperimentVariant


class Experiment:
    def __init__(self):
        self.id: int
        self.name: str
        self.unit_type: str
        self.iteration: int
        self.seed_hi: int
        self.seed_lo: int
        self.split: list[float]
        self.traffic_seed_hi: int
        self.traffic_seed_lo: int
        self.traffic_split: list[float]
        self.full_on_variant: int
        self.applications: list[ExperimentApplication]
        self.variants: list[ExperimentVariant]
        self.audience_strict: bool
        self.audience: str
