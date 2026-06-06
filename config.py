import tomllib
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class ElectrolyzerConfig:
    id: str
    name: str
    rated_h2_output: float
    rated_power: float
    rated_current: float
    warmup_time: int
    n2_purge_time: int
    min_load_ratio: float
    max_load_ratio: float
    ramp_rate_per_min: float
    overload_protection_ratio: float
    electrolyte_temp_initial: float
    electrolyte_temp_alarm: float
    electrolyte_temp_trip: float
    heat_gain_coeff: float
    cooling_coeff: float


@dataclass
class PurifierConfig:
    id: str
    name: str
    capacity: float
    mode: str


@dataclass
class TankConfig:
    id: str
    name: str
    design_pressure: float
    volume_nm3: float
    initial_pressure: float
    compression_factor: float
    max_fill_rate: float
    alarm_pressure: float
    high_pressure: float
    trip_pressure: float
    relief_target: float
    relief_rate: float


@dataclass
class PumpConfig:
    id: str
    name: str
    mode: str


@dataclass
class CoolingSystemConfig:
    pumps: Dict[str, PumpConfig]
    cooling_water_temp_initial: float
    cooling_water_temp_alarm: float
    ambient_temp: float
    pump_heat_removal: float
    pump_count: int


@dataclass
class RectifierConfig:
    id: str
    name: str
    paired_cell: str
    overload_protection_ratio: float


@dataclass
class N2SystemConfig:
    purge_time: int
    purge_flow: float


@dataclass
class SafetyConfig:
    h2_lel_one: float
    h2_lel_two: float
    h2_lel_three: float
    ventilation_rate: float


@dataclass
class SchedulerConfig:
    load_balance_tolerance: float
    target_demand_initial: float


@dataclass
class RecorderConfig:
    csv_file: str
    history_file: str


@dataclass
class GeneralConfig:
    simulation_step: int
    initial_step: int
    max_steps: int
    log_level: str


@dataclass
class PlantConfig:
    general: GeneralConfig
    electrolyzers: Dict[str, ElectrolyzerConfig]
    purifiers: Dict[str, PurifierConfig]
    tanks: Dict[str, TankConfig]
    cooling_system: CoolingSystemConfig
    rectifiers: Dict[str, RectifierConfig]
    n2_system: N2SystemConfig
    safety: SafetyConfig
    scheduler: SchedulerConfig
    recorder: RecorderConfig


def load_config(config_path: str = "config.toml") -> PlantConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    general_data = data.get("general", {})
    general = GeneralConfig(
        simulation_step=general_data.get("simulation_step", 1),
        initial_step=general_data.get("initial_step", 0),
        max_steps=general_data.get("max_steps", 1000),
        log_level=general_data.get("log_level", "INFO"),
    )

    elec_defaults = data.get("electrolyzers", {}).get("default", {})
    electrolyzers: Dict[str, ElectrolyzerConfig] = {}
    elec_count = data.get("electrolyzers", {}).get("count", 0)
    for i in range(1, elec_count + 1):
        key = f"cell{i}"
        cell_data = data.get("electrolyzers", {}).get(key, {})
        if not cell_data:
            continue
        electrolyzers[key] = ElectrolyzerConfig(
            id=cell_data.get("id", key),
            name=cell_data.get("name", key),
            rated_h2_output=cell_data.get("rated_h2_output", elec_defaults.get("rated_h2_output", 500.0)),
            rated_power=cell_data.get("rated_power", elec_defaults.get("rated_power", 2500.0)),
            rated_current=cell_data.get("rated_current", elec_defaults.get("rated_current", 5000.0)),
            warmup_time=cell_data.get("warmup_time", elec_defaults.get("warmup_time", 15)),
            n2_purge_time=cell_data.get("n2_purge_time", elec_defaults.get("n2_purge_time", 5)),
            min_load_ratio=cell_data.get("min_load_ratio", elec_defaults.get("min_load_ratio", 0.3)),
            max_load_ratio=cell_data.get("max_load_ratio", elec_defaults.get("max_load_ratio", 1.0)),
            ramp_rate_per_min=cell_data.get("ramp_rate_per_min", elec_defaults.get("ramp_rate_per_min", 0.1)),
            overload_protection_ratio=cell_data.get("overload_protection_ratio", elec_defaults.get("overload_protection_ratio", 1.1)),
            electrolyte_temp_initial=cell_data.get("electrolyte_temp_initial", elec_defaults.get("electrolyte_temp_initial", 25.0)),
            electrolyte_temp_alarm=cell_data.get("electrolyte_temp_alarm", elec_defaults.get("electrolyte_temp_alarm", 80.0)),
            electrolyte_temp_trip=cell_data.get("electrolyte_temp_trip", elec_defaults.get("electrolyte_temp_trip", 90.0)),
            heat_gain_coeff=cell_data.get("heat_gain_coeff", elec_defaults.get("heat_gain_coeff", 0.1)),
            cooling_coeff=cell_data.get("cooling_coeff", elec_defaults.get("cooling_coeff", 1.0)),
        )

    pur_defaults = data.get("purifiers", {}).get("default", {})
    purifiers: Dict[str, PurifierConfig] = {}
    pur_count = data.get("purifiers", {}).get("count", 0)
    for i in range(1, pur_count + 1):
        key = f"purifier{i}"
        pur_data = data.get("purifiers", {}).get(key, {})
        if not pur_data:
            continue
        purifiers[key] = PurifierConfig(
            id=pur_data.get("id", key),
            name=pur_data.get("name", key),
            capacity=pur_data.get("capacity", pur_defaults.get("capacity", 800.0)),
            mode=pur_data.get("mode", pur_defaults.get("mode", "standby")),
        )

    tank_defaults = data.get("tanks", {}).get("default", {})
    tanks: Dict[str, TankConfig] = {}
    tank_count = data.get("tanks", {}).get("count", 0)
    for i in range(1, tank_count + 1):
        key = f"tank{i}"
        tank_data = data.get("tanks", {}).get(key, {})
        if not tank_data:
            continue
        tanks[key] = TankConfig(
            id=tank_data.get("id", key),
            name=tank_data.get("name", key),
            design_pressure=tank_data.get("design_pressure", tank_defaults.get("design_pressure", 40.0)),
            volume_nm3=tank_data.get("volume_nm3", tank_defaults.get("volume_nm3", 500.0)),
            initial_pressure=tank_data.get("initial_pressure", 20.0),
            compression_factor=tank_data.get("compression_factor", tank_defaults.get("compression_factor", 1.2)),
            max_fill_rate=tank_data.get("max_fill_rate", tank_defaults.get("max_fill_rate", 50.0)),
            alarm_pressure=tank_data.get("alarm_pressure", tank_defaults.get("alarm_pressure", 36.0)),
            high_pressure=tank_data.get("high_pressure", tank_defaults.get("high_pressure", 38.0)),
            trip_pressure=tank_data.get("trip_pressure", tank_defaults.get("trip_pressure", 39.0)),
            relief_target=tank_data.get("relief_target", tank_defaults.get("relief_target", 35.0)),
            relief_rate=tank_data.get("relief_rate", tank_defaults.get("relief_rate", 10.0)),
        )

    cooling_data = data.get("cooling_system", {})
    pumps: Dict[str, PumpConfig] = {}
    pump_count = cooling_data.get("pump_count", 0)
    for i in range(1, pump_count + 1):
        key = f"pump{i}"
        pump_data = cooling_data.get(key, {})
        if pump_data:
            pumps[key] = PumpConfig(
                id=pump_data.get("id", key),
                name=pump_data.get("name", key),
                mode=pump_data.get("mode", "standby"),
            )

    cooling_system = CoolingSystemConfig(
        pumps=pumps,
        cooling_water_temp_initial=cooling_data.get("cooling_water_temp_initial", 25.0),
        cooling_water_temp_alarm=cooling_data.get("cooling_water_temp_alarm", 35.0),
        ambient_temp=cooling_data.get("ambient_temp", 25.0),
        pump_heat_removal=cooling_data.get("pump_heat_removal", 2.0),
        pump_count=pump_count,
    )

    rect_defaults = data.get("rectifiers", {})
    rectifiers: Dict[str, RectifierConfig] = {}
    rect_count = data.get("rectifiers", {}).get("count", 0)
    for i in range(1, rect_count + 1):
        key = f"rectifier{i}"
        rect_data = data.get("rectifiers", {}).get(key, {})
        if not rect_data:
            continue
        rectifiers[key] = RectifierConfig(
            id=rect_data.get("id", key),
            name=rect_data.get("name", key),
            paired_cell=rect_data.get("paired_cell", f"cell{i}"),
            overload_protection_ratio=rect_data.get("overload_protection_ratio", rect_defaults.get("overload_protection_ratio", 1.1)),
        )

    n2_data = data.get("n2_system", {})
    n2_system = N2SystemConfig(
        purge_time=n2_data.get("purge_time", 5),
        purge_flow=n2_data.get("purge_flow", 10.0),
    )

    safety_data = data.get("safety", {})
    safety = SafetyConfig(
        h2_lel_one=safety_data.get("h2_lel_one", 0.01),
        h2_lel_two=safety_data.get("h2_lel_two", 0.02),
        h2_lel_three=safety_data.get("h2_lel_three", 0.04),
        ventilation_rate=safety_data.get("ventilation_rate", 0.005),
    )

    sched_data = data.get("scheduler", {})
    scheduler = SchedulerConfig(
        load_balance_tolerance=sched_data.get("load_balance_tolerance", 0.05),
        target_demand_initial=sched_data.get("target_demand_initial", 800.0),
    )

    rec_data = data.get("recorder", {})
    recorder = RecorderConfig(
        csv_file=rec_data.get("csv_file", "simulation_data.csv"),
        history_file=rec_data.get("history_file", "simulation_history.json"),
    )

    return PlantConfig(
        general=general,
        electrolyzers=electrolyzers,
        purifiers=purifiers,
        tanks=tanks,
        cooling_system=cooling_system,
        rectifiers=rectifiers,
        n2_system=n2_system,
        safety=safety,
        scheduler=scheduler,
        recorder=recorder,
    )
