"""Moving-average crossover signal generation."""

from dataclasses import dataclass

from ashare_lab.domain.market import MarketBar


@dataclass(frozen=True, slots=True)
class MovingAverageCross:
    """Stay long while the short close average exceeds the long average."""

    short_window: int
    long_window: int

    def targets(self, bars: tuple[MarketBar, ...]) -> tuple[float, ...]:
        """Return one close-generated target for every input bar."""
        closes = [bar.close for bar in bars]
        targets: list[float] = []
        for index in range(len(closes)):
            if index + 1 < self.long_window:
                targets.append(0.0)
                continue
            short_start = index + 1 - self.short_window
            long_start = index + 1 - self.long_window
            short_average = sum(closes[short_start : index + 1]) / self.short_window
            long_average = sum(closes[long_start : index + 1]) / self.long_window
            targets.append(1.0 if short_average > long_average else 0.0)
        return tuple(targets)
