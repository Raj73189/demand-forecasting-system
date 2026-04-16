from dataclasses import asdict, dataclass

@dataclass
class HorizonDemand:
    forecast: float
    is_high_demand: bool

    def __post_init__(self) -> None:
        """Normalize and validate schema values."""
        self.forecast = float(self.forecast)
        if self.forecast < 0:
            raise ValueError("forecast must be non-negative")
        self.is_high_demand = bool(self.is_high_demand)

    def to_dict(self) -> dict[str, float | bool]:
        """Return a JSON-serializable dictionary representation."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, float | bool]) -> "HorizonDemand":
        """Construct a schema instance from a plain dictionary."""
        return cls(
            forecast=float(data["forecast"]),
            is_high_demand=bool(data["is_high_demand"]),
        )