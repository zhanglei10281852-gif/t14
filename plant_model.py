from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from config import (
    PlantConfig,
    ElectrolyzerConfig,
    PurifierConfig,
    TankConfig,
    PumpConfig,
    RectifierConfig,
)


class CellState(Enum):
    STOPPED = "stopped"
    N2_PURGE = "n2_purge"
    WARMUP = "warmup"
    RUNNING = "running"
    LOAD_REDUCING = "load_reducing"
    EMERGENCY_STOP = "emergency_stop"
    FAULT = "fault"


class PurifierState(Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    FAULT = "fault"


class PumpState(Enum):
    ACTIVE = "active"
    STANDBY = "standby"
    FAULT = "fault"
    OFF = "off"


class AlarmLevel(Enum):
    NONE = "none"
    LEVEL_1 = "level_1"
    LEVEL_2 = "level_2"
    LEVEL_3 = "level_3"


@dataclass
class Electrolyzer:
    cfg: ElectrolyzerConfig
    state: CellState = CellState.STOPPED
    load_ratio: float = 0.0
    target_load_ratio: float = 0.0
    electrolyte_temp: float = 25.0
    current: float = 0.0
    power: float = 0.0
    h2_output: float = 0.0
    state_timer: int = 0
    run_time_total: int = 0
    fault_code: str = ""
    interlock_active: List[str] = field(default_factory=list)
    load_limit_ratio: float = 1.0

    @property
    def min_load_ratio(self) -> float:
        return self.cfg.min_load_ratio

    @property
    def max_load_ratio(self) -> float:
        return self.cfg.max_load_ratio * self.load_limit_ratio

    @property
    def is_ramp_rate(self) -> float:
        return self.cfg.ramp_rate_per_min

    def start_purge(self) -> bool:
        if self.state in (CellState.STOPPED, CellState.FAULT):
            self.state = CellState.N2_PURGE
            self.state_timer = 0
            return True
        return False

    def start_warmup(self) -> bool:
        if self.state == CellState.N2_PURGE and self.state_timer >= self.cfg.n2_purge_time:
            self.state = CellState.WARMUP
            self.state_timer = 0
            return True
        return False

    def start_running(self) -> bool:
        if self.state == CellState.WARMUP and self.state_timer >= self.cfg.warmup_time:
            self.state = CellState.RUNNING
            self.load_ratio = self.cfg.min_load_ratio
            self.target_load_ratio = self.cfg.min_load_ratio
            self.state_timer = 0
            return True
        return False

    def stop(self) -> None:
        if self.state in (CellState.RUNNING, CellState.LOAD_REDUCING):
            self.state = CellState.LOAD_REDUCING
            self.target_load_ratio = 0.0

    def emergency_stop(self, fault_code: str = "emergency") -> None:
        self.state = CellState.EMERGENCY_STOP
        self.load_ratio = 0.0
        self.target_load_ratio = 0.0
        self.current = 0.0
        self.power = 0.0
        self.h2_output = 0.0
        self.fault_code = fault_code

    def reset_from_fault(self) -> bool:
        if self.state in (CellState.EMERGENCY_STOP, CellState.FAULT):
            self.state = CellState.STOPPED
            self.fault_code = ""
            self.interlock_active = []
            self.load_limit_ratio = 1.0
            return True
        return False

    def update_load(self) -> None:
        if self.state not in (CellState.RUNNING, CellState.LOAD_REDUCING):
            return
        ramp = self.cfg.ramp_rate_per_min
        if self.target_load_ratio > self.load_ratio:
            self.load_ratio = min(self.load_ratio + ramp, self.target_load_ratio, self.max_load_ratio)
        elif self.target_load_ratio < self.load_ratio:
            self.load_ratio = max(self.load_ratio - ramp, self.target_load_ratio)
        if self.state == CellState.LOAD_REDUCING and self.load_ratio <= 0.01:
            self.state = CellState.STOPPED
            self.load_ratio = 0.0
            self.target_load_ratio = 0.0

    def update_temp(self, cooling_water_temp: float) -> None:
        if self.state == CellState.RUNNING or self.state == CellState.LOAD_REDUCING:
            heat_gain = self.load_ratio * self.cfg.heat_gain_coeff
            temp_diff = self.electrolyte_temp - cooling_water_temp
            heat_loss = self.cfg.cooling_coeff * temp_diff / 50.0
            self.electrolyte_temp += heat_gain - heat_loss
        else:
            temp_diff = self.electrolyte_temp - cooling_water_temp
            self.electrolyte_temp -= temp_diff * 0.05

    def calc_output(self) -> None:
        if self.state in (CellState.RUNNING, CellState.LOAD_REDUCING):
            self.h2_output = self.cfg.rated_h2_output * self.load_ratio
            self.power = self.cfg.rated_power * self.load_ratio
            self.current = self.cfg.rated_current * self.load_ratio
        else:
            self.h2_output = 0.0
            self.power = 0.0
            self.current = 0.0


@dataclass
class Purifier:
    cfg: PurifierConfig
    state: PurifierState = PurifierState.STANDBY
    input_flow: float = 0.0
    output_flow: float = 0.0

    def activate(self) -> None:
        self.state = PurifierState.ACTIVE

    def deactivate(self) -> None:
        self.state = PurifierState.STANDBY

    def process(self, input_flow: float) -> float:
        if self.state == PurifierState.ACTIVE:
            processed = min(input_flow, self.cfg.capacity)
            self.input_flow = input_flow
            self.output_flow = processed
            return processed
        self.input_flow = 0.0
        self.output_flow = 0.0
        return 0.0


@dataclass
class Tank:
    cfg: TankConfig
    pressure: float = 20.0
    fill_rate: float = 0.0
    is_filling: bool = False
    is_relieving: bool = False
    interlock_active: List[str] = field(default_factory=list)
    alarm_level: AlarmLevel = AlarmLevel.NONE

    @property
    def volume_m3(self) -> float:
        return self.cfg.volume_nm3 / self.cfg.design_pressure

    def fill(self, amount_nm3_per_step: float) -> float:
        if self.is_relieving or self.pressure >= self.cfg.high_pressure:
            return 0.0
        max_fill_per_step = self.cfg.max_fill_rate / 60.0
        actual_fill = min(amount_nm3_per_step, max_fill_per_step)
        if self.pressure + self._delta_p(max_fill_per_step) >= self.cfg.high_pressure:
            remaining_pressure_diff = self.cfg.high_pressure - self.pressure
            if remaining_pressure_diff <= 0:
                self.fill_rate = 0.0
                return 0.0
            actual_fill = self._delta_nm3(remaining_pressure_diff)
            actual_fill = min(actual_fill, max_fill_per_step)
        self.pressure += self._delta_p(actual_fill)
        self.fill_rate = actual_fill * 60.0
        self.is_filling = True
        return actual_fill

    def _delta_p(self, amount_nm3: float) -> float:
        return amount_nm3 / (self.volume_m3 * self.cfg.compression_factor)

    def _delta_nm3(self, delta_p: float) -> float:
        return delta_p * self.volume_m3 * self.cfg.compression_factor

    def relief(self) -> float:
        if self.pressure <= self.cfg.relief_target:
            self.is_relieving = False
            return 0.0
        relief_amount_p = self.cfg.relief_rate
        new_pressure = max(self.pressure - relief_amount_p, self.cfg.relief_target)
        released = self._delta_nm3(self.pressure - new_pressure)
        self.pressure = new_pressure
        self.is_relieving = True
        return released

    def reset_fill_state(self) -> None:
        self.is_filling = False
        self.fill_rate = 0.0


@dataclass
class CoolingPump:
    cfg: PumpConfig
    state: PumpState = PumpState.STANDBY
    flow_rate: float = 0.0

    def start(self) -> None:
        if self.state == PumpState.STANDBY:
            self.state = PumpState.ACTIVE
            self.flow_rate = 1.0

    def stop(self) -> None:
        self.state = PumpState.STANDBY
        self.flow_rate = 0.0

    def set_fault(self) -> None:
        self.state = PumpState.FAULT
        self.flow_rate = 0.0

    def reset_fault(self) -> None:
        if self.state == PumpState.FAULT:
            self.state = PumpState.STANDBY


@dataclass
class Rectifier:
    cfg: RectifierConfig
    output_current: float = 0.0
    is_tripped: bool = False
    trip_reason: str = ""

    def trip(self, reason: str) -> None:
        self.is_tripped = True
        self.trip_reason = reason
        self.output_current = 0.0

    def reset(self) -> None:
        self.is_tripped = False
        self.trip_reason = ""


@dataclass
class PlantState:
    step: int = 0
    electrolyzers: Dict[str, Electrolyzer] = field(default_factory=dict)
    purifiers: Dict[str, Purifier] = field(default_factory=dict)
    tanks: Dict[str, Tank] = field(default_factory=dict)
    cooling_pumps: Dict[str, CoolingPump] = field(default_factory=dict)
    rectifiers: Dict[str, Rectifier] = field(default_factory=dict)
    cooling_water_temp: float = 25.0
    h2_concentration: float = 0.0
    fire_alarm_active: bool = False
    esd_active: bool = False
    esd_reset_code: str = ""
    total_h2_produced: float = 0.0
    total_energy_kwh: float = 0.0
    target_demand: float = 0.0
    ventilation_active: bool = False
    level1_alarms: List[str] = field(default_factory=list)
    level2_alarms: List[str] = field(default_factory=list)
    level3_alarms: List[str] = field(default_factory=list)
    interlock_log: List[dict] = field(default_factory=list)
    command_queue: List[dict] = field(default_factory=list)
    active_fill_target: Dict[str, float] = field(default_factory=dict)

    def add_interlock_log_entry(self, level: str, device: str, action: str, reason: str) -> None:
        entry = {
            "step": self.step,
            "level": level,
            "device": device,
            "action": action,
            "reason": reason,
        }
        self.interlock_log.append(entry)


def create_plant_state(config: PlantConfig) -> PlantState:
    state = PlantState()
    state.target_demand = config.scheduler.target_demand_initial
    state.cooling_water_temp = config.cooling_system.cooling_water_temp_initial

    for key, cfg in config.electrolyzers.items():
        cell = Electrolyzer(cfg=cfg)
        cell.electrolyte_temp = cfg.electrolyte_temp_initial
        state.electrolyzers[key] = cell

    for key, cfg in config.purifiers.items():
        purifier = Purifier(cfg=cfg)
        if cfg.mode == "active":
            purifier.state = PurifierState.ACTIVE
        state.purifiers[key] = purifier

    for key, cfg in config.tanks.items():
        tank = Tank(cfg=cfg)
        tank.pressure = cfg.initial_pressure
        state.tanks[key] = tank

    for key, cfg in config.cooling_system.pumps.items():
        pump = CoolingPump(cfg=cfg)
        if cfg.mode == "active":
            pump.state = PumpState.ACTIVE
            pump.flow_rate = 1.0
        state.cooling_pumps[key] = pump

    for key, cfg in config.rectifiers.items():
        rectifier = Rectifier(cfg=cfg)
        state.rectifiers[key] = rectifier

    return state
